from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework import status
from sentence_transformers import SentenceTransformer
from sklearn.preprocessing import normalize
import fitz  # PyMuPDF
import psycopg2
import uuid
import re
import os
import time
from datetime import datetime

# PostgreSQL DB config
DB_CONFIG = {
    "dbname": "chatbot_new",
    "user": "postgres",
    "password": "Admin@2022",
    "host": "localhost",
    "port": "5432"
}

# SentenceTransformer wrapper
class SentenceModel:
    def __init__(self):
        self.model = SentenceTransformer(r"C:\inetpub\wwwroot\Websitebot\all-MiniLM-L6-v2")

    def encode(self, texts, convert_to_numpy=True):
        return self.model.encode(texts, convert_to_numpy=convert_to_numpy)

# PDFProcessor with cosine similarity from raw SQL
class PDFProcessor:
    def __init__(self, model):
        self.model = model

    def search(self, query, top_k=1, min_score=0.33):
        query_vec = normalize(self.model.encode([query]))[0].tolist()

        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        sql = """
        WITH query_embedding AS (
            SELECT ordinality AS idx, val
            FROM unnest(%s::FLOAT8[]) WITH ORDINALITY AS t(val, ordinality)
        ),
        expanded_embeddings AS (
            SELECT 
                kbe.id, 
                kbe.text,
                t.val AS val,
                t.ordinality AS idx
            FROM DGIS kbe,
            unnest(kbe.vector) WITH ORDINALITY AS t(val, ordinality)
        ),
        dot_products AS (
            SELECT 
                e.id,
                e.text,
                SUM(e.val * q.val) AS dot_product,
                SQRT(SUM(e.val * e.val)) AS norm_a,
                SQRT(SUM(q.val * q.val)) AS norm_b
            FROM expanded_embeddings e
            JOIN query_embedding q ON e.idx = q.idx
            GROUP BY e.id, e.text
        )
        SELECT 
            id,
            text,
            (dot_product / (norm_a * norm_b)) AS cosine_similarity
        FROM dot_products
        ORDER BY cosine_similarity DESC
        LIMIT %s;
        """

        start_time = time.time()
        cursor.execute(sql, (query_vec, top_k))
        results = cursor.fetchall()
        duration = round(time.time() - start_time, 4)

        cursor.close()
        conn.close()

        filtered = [
            {"text": row[1], "score": round(row[2], 4)}
            for row in results if row[2] and row[2] >= min_score
        ]

        return filtered, duration

# Global objects
model = SentenceModel()
processor = PDFProcessor(model)

# -------------------- PDF Upload API --------------------

class PDFUploadAPIView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request):
        pdf_file = request.FILES.get('file')
        if not pdf_file:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
            text = "\n".join([page.get_text() for page in doc])

            pattern = re.compile(r'(Q\s*.*?)(A\s*.*?)(?=\s*Q|$)', re.DOTALL)
            matches = re.findall(pattern, text)
            chunks = []

            for question, answer in matches:
                question = re.sub(r'^\d+\.\s*', '', question).strip()
                answer = re.sub(r'^\d+\.\s*', '', answer).strip()
                chunks.append(f"{question}\n{answer}")

            if not chunks:
                return Response({"message": "No Q&A pairs found in the document"}, status=status.HTTP_204_NO_CONTENT)

            embeddings = model.encode(chunks)
            embeddings = normalize(embeddings)

            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS DGIS (
                    id UUID PRIMARY KEY,
                    text TEXT,
                    vector FLOAT8[]
                );
            """)

            for chunk, vec in zip(chunks, embeddings):
                cursor.execute("""
                    INSERT INTO DGIS (id, text, vector)
                    VALUES (%s, %s, %s)
                """, (str(uuid.uuid4()), chunk, vec.tolist()))

            conn.commit()
            cursor.close()
            conn.close()

            return Response({"message": f"{len(chunks)} Q&A chunks embedded and stored."}, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# -------------------- Ask PDF API --------------------

class AskPDFAPIView(APIView):
    ALIAS_MAP = {
        "cms": "candidate management system",
        "ETC": "Empowered Tech Committee",
        "appln": "application",
        "asdc": "Army Software Development Centre",
        "hrms":"Human Resource Management System"
    }

    def expand_query(self, query):
        words = query.lower().split()
        expanded = " ".join([self.ALIAS_MAP.get(w, w) for w in words])
        if "how to login" in expanded or "login" in expanded:
            expanded += " in candidate management system"
        return expanded

    def log_question(self, question, expanded_query, answer, link=None, duration=0.0, scores=None):
        log_path = os.path.join("logs", "questions.txt")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {question}\n")
            f.write(f"Question: {question}\n")
            f.write(f"Expanded Query: {expanded_query}\n")
            f.write(f"Answer: {answer}\n")
            if link:
                f.write(f"Link: {link}\n")
            f.write(f"Query Time: {duration} sec\n")
            if scores:
                f.write(f"Similarity Scores: {scores}\n")
            f.write("=" * 50 + "\n")

    def add_feedback(self, feedback_type):
        log_path = os.path.join("logs", "questions.txt")
        if not os.path.exists(log_path):
            return False, "questions.txt file not found."

        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == "=" * 50:
                feedback_line = f"Feedback: {feedback_type}\n"
                lines.insert(i, feedback_line)
                break
        else:
            return False, "No question block separator found."

        with open(log_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        return True, "Feedback added."

    def post(self, request):
        question = request.data.get("query")
        feedback_type = request.data.get("feedback")

        if not question:
            return Response({"error": "Missing 'query' in request"}, status=status.HTTP_400_BAD_REQUEST)

        expanded_query = self.expand_query(question)
        results, duration = processor.search(expanded_query)

        if not results:
            return Response({
                "context": [],
                "answer": "Please ask a question within the scope of the website.",
                "link": None,
                "duration": duration,
                "scores": []
            })

        context_chunks = [r["text"] for r in results]
        scores = [r["score"] for r in results]
        answer = ""
        link = None

        for chunk in context_chunks:
            if "A" in chunk:
                answer = chunk.split("A", 1)[-1].strip()
            found_links = re.findall(r'https?://[^\s]+', chunk)
            if found_links:
                link = found_links[0]

        answer = answer.replace("Link :", "").replace("Link:-", "").replace("Link:", "").strip()
        if link:
            answer = answer.replace(link, "").strip()
            link = f'<a href="{link}" target="_blank">{link}</a>'

        self.log_question(question, expanded_query, answer, link, duration, scores)

        if feedback_type:
            if feedback_type not in ["like", "dislike"]:
                return Response({"error": "Invalid feedback type"}, status=status.HTTP_400_BAD_REQUEST)
            success, message = self.add_feedback(feedback_type)
            if success:
                return Response({"message": message})
            return Response({"error": message}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "context": context_chunks,
            "answer": answer,
            "link": link,
            "duration": duration,
            "scores": scores
        })





# views.py

from django.contrib.auth import authenticate
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import AllowAny

from api.serializer import RegisterSerializer, LoginSerializer


# Register View
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]


# Login View
class LoginView(generics.GenericAPIView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            password = serializer.validated_data['password']

            # Authenticate user
            user = authenticate(request, username=email, password=password)

            if user is not None:
                # Generate JWT token
                refresh = RefreshToken.for_user(user)
                access_token = str(refresh.access_token)
                refresh_token = str(refresh)  # Generate refresh token
                return Response({
                    "access_token": access_token,
                    "refresh_token": refresh_token,  # Send refresh token
                    "user": {
                        "id": user.id,
                        "email": user.email,
                    }
                }, status=status.HTTP_200_OK)
            else:
                return Response({"error": "Invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
