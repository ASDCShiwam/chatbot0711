from rest_framework.views import APIView
from django.views.decorators.csrf import csrf_exempt
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
from django.utils.text import slugify
import json
from django.conf import settings
import socket
from django.http import JsonResponse
from django.db import connection
from rest_framework.decorators import api_view
import bcrypt
import psycopg2
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
# PostgreSQL DB config
DB_CONFIG = {
    "dbname": "chatbot",
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

    def search(self, query, collection_name, top_k=1, min_score=0.33):
    # Validate collection_name to prevent SQL injection
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', collection_name):
            raise ValueError("Invalid collection name")

        query_vec = normalize(self.model.encode([query]))[0].tolist()

        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # Use f-string to inject table name safely
        sql = f"""
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
            FROM {collection_name} kbe,
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

    def searchwiththinking(self, query, collection_name, top_k=5, min_score=0.0):
    # Validate collection_name to prevent SQL injection
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', collection_name):
            raise ValueError("Invalid collection name")
        collection_name = f"chatbot_{collection_name}" # for ADN remove chatbot
        query_vec = normalize(self.model.encode([query]))[0].tolist()

        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # Use f-string to inject table name safely
        sql = f"""
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
            FROM {collection_name} kbe,
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
        collection_name = request.POST.get("collection_name")

        if not pdf_file:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)
        if not collection_name:
            return Response({"error": "Missing collection_name"}, status=status.HTTP_400_BAD_REQUEST)

        # Sanitize collection name to prevent SQL injection
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', collection_name):
            return Response({"error": "Invalid collection_name. Use only alphanumeric and underscore."}, status=status.HTTP_400_BAD_REQUEST)

        table_name = f"chatbot_{collection_name}"

        try:
            # Read PDF and sanitize null bytes
            doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
            text = "\n".join([page.get_text().replace('\x00', '') for page in doc])

            # Extract Q&A pairs
            pattern = re.compile(r'(Q:\s*.*?)(A:\s*.*?)(?=\s*Q:|$)', re.DOTALL)
            matches = re.findall(pattern, text)
            chunks = []

            for question, answer in matches:
                question = re.sub(r'^\d+\.\s*', '', question).strip().replace('\x00', '')
                answer = re.sub(r'^\d+\.\s*', '', answer).strip().replace('\x00', '')
                clean_chunk = f"{question}\n{answer}"
                chunks.append(clean_chunk)

            if not chunks:
                return Response({"message": "No Q&A pairs found in the document"}, status=status.HTTP_204_NO_CONTENT)

            # Encode and normalize
            embeddings = model.encode(chunks)
            embeddings = normalize(embeddings)

            # Connect to PostgreSQL
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            # Create table if it doesn't exist
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id UUID PRIMARY KEY,
                    text TEXT,
                    vector FLOAT8[]
                );
            """)

            # Insert data
            for chunk, vec in zip(chunks, embeddings):
                chunk = chunk.replace('\x00', '')  # Final safety check
                cursor.execute(
                    f"""INSERT INTO {table_name} (id, text, vector) VALUES (%s, %s, %s)""",
                    (str(uuid.uuid4()), chunk, vec.tolist())
                )

            conn.commit()
            cursor.close()
            conn.close()

            return Response({"message": f"{len(chunks)} Q&A chunks embedded and stored in '{table_name}'."}, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": f"Internal Server Error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# -------------------- Ask PDF API --------------------

class AskPDFAPIView(APIView):
    ALIAS_MAP = {
        "cms": "candidate management system",
        "etc": "Empowered Tech Committee",
        "appln": "application",
        "asdc": "Army Software Development Centre",
        # "dgis":"director general information system",
        "dte":"director",
        "gen":"general",
        "adg":"Additional Directors Generally ",
        "dg":"Director General "
    }

    def expand_query(self, query):
        words = query.lower().split()
        expanded = " ".join([self.ALIAS_MAP.get(w, w) for w in words])
        if "how to login" in expanded or "login" in expanded:
            expanded += " in candidate management system"
        return expanded

    # Method to log question data into the PostgreSQL database
    def log_question_to_db(self, request, question, expanded_query, answer, link=None, duration=0.0, scores=None, feedback=None,collection_name=None):
        # print("-- Logging to DB")

        # Establish a connection to PostgreSQL
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # Prepare the data
        query_time = datetime.now()
        similarity_scores = json.dumps(scores) if scores else None

        ip_address = request.META.get('REMOTE_ADDR')
        domain = request.get_host()
        computer_name = socket.gethostname()

        # Insert the log data into the database
        cursor.execute("""
        INSERT INTO chatbot_logs (
            question, expanded_query, answer, link, query_time,
            similarity_scores, feedback,
            domain, ip_address, computer_name,collection_name
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        question, expanded_query, answer, link, query_time,
        similarity_scores, feedback,
        domain, ip_address, computer_name,collection_name
    ))

        conn.commit()
        cursor.close()
        conn.close()

        # print("-- Log inserted into DB")
    
    def update_feedback_in_db(self, question, feedback_type):
        print(f"Updating feedback for question: {question} with feedback type: {feedback_type}")
        # Establish a connection to PostgreSQL
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # Update the feedback in the database for the given question
        cursor.execute("""
            UPDATE chatbot_logs
            SET feedback = %s
            WHERE question = %s
        """, (feedback_type, question))

        # Commit the transaction
        conn.commit()

        # Close the connection
        cursor.close()
        conn.close()
        print(f"Feedback '{feedback_type}' updated for question: {question}")

    def post(self, request):
        question = request.data.get("query")
        feedback_type = request.data.get("feedback")
        collection_name = request.data.get("collection_name")
        if not collection_name:
            return Response({"error": "Missing 'collection_name' in request"}, status=status.HTTP_400_BAD_REQUEST)


        if not question:
            return Response({"error": "Missing 'query' in request"}, status=status.HTTP_400_BAD_REQUEST)

        expanded_query = self.expand_query(question)
        results, duration = processor.search(expanded_query,collection_name)

        if not results:
            self.log_question_to_db(
            request=request,
            question=question,
            expanded_query=expanded_query,
            answer="Please ask a question within the scope of the website.",
            link=None,
            duration=duration,
            scores=[],
            feedback='dislike',
            collection_name=collection_name
        )
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
            if "A:" in chunk:
                answer = chunk.split("A:", 1)[-1].strip()
            
            # Check if the chunk contains a link
            # Regex to find any URL starting with http or https
            found_links = re.findall(r'https?://[^\s]+', chunk)
            if found_links:
                link = found_links[0] # Take the first link found


        answer = answer.replace("Link :", "").replace("Link:-", "").replace("Link:", "").strip()
        if link:
            answer = answer.replace(link, "").strip()
            link = f'<a href="{link}" target="_blank">{link}</a>'

        # Log the question and answer data to PostgreSQL database
        self.log_question_to_db(request, question, expanded_query, answer, link, duration, scores, feedback_type,collection_name)

        # Handle feedback (like/dislike)
        if feedback_type:
            print(f"Received feedback: {feedback_type} for question: {question}")   
            if feedback_type not in ["like", "dislike"]:
                return Response({"error": "Invalid feedback type"}, status=status.HTTP_400_BAD_REQUEST)
            # You can add feedback logic here (update the feedback in DB if needed)
            # For now, feedback will be logged with the question as part of the original insert.
            self.update_feedback_in_db(question, feedback_type)

        return Response({
            "context": context_chunks,
            "answer": answer,
            "link": link,
            "duration": duration,
            "scores": scores
        })



class FeedbackUpdateAPIView(APIView):
    def post(self, request):
        question = request.data.get("query")
        feedback_type = request.data.get("feedback")

        if not question or not feedback_type:
            return Response({"error": "Missing 'query' or 'feedback'"}, status=status.HTTP_400_BAD_REQUEST)

        if feedback_type not in ["like", "dislike"]:
            return Response({"error": "Invalid feedback type"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Connect to PostgreSQL
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            # Use CTE to update the most recent matching row
            cursor.execute("""
                WITH latest_log AS (
                    SELECT id FROM chatbot_logs
                    WHERE question = %s
                    ORDER BY query_time DESC
                    LIMIT 1
                )
                UPDATE chatbot_logs
                SET feedback = %s
                WHERE id IN (SELECT id FROM latest_log)
            """, (question, feedback_type))

            conn.commit()
            cursor.close()
            conn.close()

            return Response({"message": f"Feedback '{feedback_type}' updated for question: '{question}'"})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class PDFStoreAPIView(APIView):
    parser_classes = [MultiPartParser]

    
    def post(self, request):
        pdf_file = request.FILES.get("file")
        collection_name = request.POST.get("collection_name")

        if not pdf_file or not collection_name:
            return Response({"error": "Missing file or collection name"}, status=status.HTTP_400_BAD_REQUEST)

        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', collection_name):
            return Response({"error": "Invalid collection name"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Ensure media folder exists
            os.makedirs(settings.MEDIA_ROOT, exist_ok=True)

            # Sanitize and generate unique filename
            name, ext = os.path.splitext(pdf_file.name)
            safe_name = slugify(name) + "_" + str(uuid.uuid4())[:8] + ext
            media_file_path = os.path.join(settings.MEDIA_ROOT, safe_name)

            # Save file to disk
            with open(media_file_path, 'wb+') as destination:
                for chunk in pdf_file.chunks():
                    destination.write(chunk)

            # Metadata
            file_size_kb = round(pdf_file.size / 1024, 2)
            file_id = str(uuid.uuid4())
            created_at = datetime.now()

            # Store metadata in DB
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS uploaded_pdfs (
                    id UUID PRIMARY KEY,
                    collection_name TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    size_kb FLOAT,
                    file_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("SELECT 1 FROM uploaded_pdfs WHERE collection_name = %s LIMIT 1;", (collection_name,))
            if cursor.fetchone():
                cursor.close()
                conn.close()
                return Response({"error": "Collection name already exists"}, status=status.HTTP_400_BAD_REQUEST)

            cursor.execute("""
                INSERT INTO uploaded_pdfs (id, collection_name, filename, size_kb, file_path, created_at)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (file_id, collection_name, safe_name, file_size_kb, media_file_path, created_at))

            conn.commit()
            cursor.close()
            conn.close()

            return Response({
                "message": "PDF uploaded and stored successfully",
                "id": file_id,
                "filename": safe_name,
                "collection_name": collection_name,
                "size_kb": file_size_kb,
                "file_url": request.build_absolute_uri(settings.MEDIA_URL + safe_name),
                "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S")
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def patch(self, request):
        pdf_file = request.FILES.get("file")
        collection_name = request.POST.get("collection_name")

        if not pdf_file or not collection_name:
            return Response({"error": "Missing file or collection name"}, status=status.HTTP_400_BAD_REQUEST)

        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', collection_name):
            return Response({"error": "Invalid collection name"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            os.makedirs(settings.MEDIA_ROOT, exist_ok=True)

            name, ext = os.path.splitext(pdf_file.name)
            safe_name = slugify(name) + "_" + str(uuid.uuid4())[:8] + ext
            media_file_path = os.path.join(settings.MEDIA_ROOT, safe_name)

            with open(media_file_path, 'wb+') as destination:
                for chunk in pdf_file.chunks():
                    destination.write(chunk)

            file_size_kb = round(pdf_file.size / 1024, 2)
            file_id = str(uuid.uuid4())
            created_at = datetime.now()

            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            # ✅ Ensure collection already exists
            cursor.execute("SELECT 1 FROM uploaded_pdfs WHERE collection_name = %s LIMIT 1;", (collection_name,))
            if not cursor.fetchone():
                cursor.close()
                conn.close()
                return Response({"error": "Collection name does not exist"}, status=status.HTTP_400_BAD_REQUEST)

            # Insert new file for existing collection
            cursor.execute("""
                INSERT INTO uploaded_pdfs (id, collection_name, filename, size_kb, file_path, created_at)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (file_id, collection_name, safe_name, file_size_kb, media_file_path, created_at))

            conn.commit()
            cursor.close()
            conn.close()

            return Response({
                "message": f"PDF added to existing collection '{collection_name}'",
                "id": file_id,
                "filename": safe_name,
                "collection_name": collection_name,
                "size_kb": file_size_kb,
                "file_url": request.build_absolute_uri(settings.MEDIA_URL + safe_name),
                "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S")
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    def get(self, request):
    # Get optional filter from query string
        collection_filter = request.query_params.get("collection")

        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            # Build query based on whether filter is present
            if collection_filter:
                cursor.execute("""
                    SELECT id, collection_name, filename, size_kb, created_at
                    FROM uploaded_pdfs
                    WHERE collection_name = %s
                    ORDER BY created_at DESC;
                """, (collection_filter,))
            else:
                cursor.execute("""
                    SELECT id, collection_name, filename, size_kb, created_at
                    FROM uploaded_pdfs
                    ORDER BY created_at DESC;
                """)

            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # Format rows into JSON-serializable dictionaries
            data = [
                {
                    "id": str(row[0]),
                    "collection_name": row[1],
                    "filename": row[2],
                    "size_kb": row[3],
                    "created_at": row[4].strftime("%Y-%m-%d %H:%M:%S"),
                    "file_url": f"{request.build_absolute_uri(settings.MEDIA_URL)}{row[2]}"

                    
                }
                for row in rows
            ]

            return Response(data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class FilesByCollectionAPIView(APIView):
    def get(self, request, collection_name):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, filename, size_kb FROM uploaded_pdfs
                WHERE collection_name = %s
                ORDER BY created_at DESC
            """, (collection_name,))
            files = cursor.fetchall()
            cursor.close()
            conn.close()

            return Response([
                {"id": str(row[0]), "filename": row[1], "size_kb": row[2]}
                for row in files
            ])
        except Exception as e:
            return Response({"error": str(e)}, status=500)
        

class CollectionDataView(APIView):
    def get(self, request):
        collection_name = request.query_params.get("collection_name")

        if not collection_name:
            return Response({"error": "Missing collection_name"}, status=status.HTTP_400_BAD_REQUEST)

        # Sanitize table name to avoid SQL injection
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', collection_name):
            return Response({"error": "Invalid collection_name"}, status=status.HTTP_400_BAD_REQUEST)

        table_name = f"chatbot_{collection_name}"

        try:
            conn = psycopg2.connect(**DB_CONFIG)
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT id, text FROM {table_name} ORDER BY id LIMIT 100")
                rows = cursor.fetchall()
                data = [{"id": row[0], "text": row[1]} for row in rows]
            return Response({"data": data}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

class DeleteChunkView(APIView):
      def post(self, request, collection_name, id):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            with conn.cursor() as cursor:
                # Build a safe SQL query with dynamic table name
                cursor.execute(f"DELETE FROM {collection_name} WHERE id = %s;", [id])

                # cursor.execute(delete_query, [str(id)])  # UUID as string

                if cursor.rowcount == 0:
                    return Response({"error": "Chunk not found"}, status=status.HTTP_404_NOT_FOUND)

                conn.commit()

            return Response({"message": f"Chunk deleted from {collection_name} successfully"}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error":str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        

@api_view(["GET"])
def get_chatbot_logs_raw(request):
    feedback_filter = request.GET.get("feedback")  # Optional: like/dislike
    try:
        with connection.cursor() as cursor:
            # Base query excluding logs where the question is "warmup"
            base_query = """
                SELECT question, answer, feedback, query_time, domain
                FROM chatbot_logs
                WHERE question != 'warmup'  -- Exclude "warmup" questions
            """
            # Modify query based on feedback filter
            if feedback_filter in ["like", "dislike"]:
                query = base_query + " AND feedback = %s ORDER BY query_time DESC"
                cursor.execute(query, [feedback_filter])
            else:
                query = base_query + " ORDER BY query_time DESC"
                cursor.execute(query)
            rows = cursor.fetchall()
        # Format response
        logs = []
        for row in rows:
            ts = row[3]
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts)
            logs.append({
                "id": str(uuid.uuid4()),  # Generate a unique ID for each log
                "question": row[0],
                "answer": row[1],
                "feedback": row[2],
                "timestamp": ts_str,
                "domain": f"{row[4]}s"
            })
        return JsonResponse({"logs": logs})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    

class DomainListView(APIView):
    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("SELECT DISTINCT domain FROM chatbot_logs WHERE domain IS NOT NULL")
            rows = cursor.fetchall()
        domains = [row[0] for row in rows]
        return Response({"domains": domains})


class DomainLogView(APIView):
    def get(self, request):
        domain = request.GET.get('domain')
        if not domain:
            return Response({"error": "Missing 'domain' parameter"}, status=400)

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT question, answer, feedback, query_time, domain
                FROM chatbot_logs
                WHERE domain = %s
                ORDER BY query_time DESC
            """, [domain])
            rows = cursor.fetchall()

        logs = [
            {
                "question": row[0],
                "answer": row[1],
                "feedback": row[2],
                "query_time": row[3],
                "domain": row[4],
            }
            for row in rows
        ]
        return Response({"logs": logs})





class RawLoginNoSerializerAPIView(APIView):
    """
    POST /api/auth/raw-login/
    body: { "username": "...", "password": "..." }
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    @csrf_exempt
    def post(self, request):
        # --- Basic input handling (no serializer) ---
        data = request.data or {}
        username = data.get("username")
        password = data.get("password")

        if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
            return Response(
                {"detail": "username and password are required non-empty strings."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # --- Lookup user in Postgres with psycopg2 ---
        try:
            with psycopg2.connect(**DB_CONFIG) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, password_hash, is_active
                        FROM app_users
                        WHERE username = %s
                        LIMIT 1
                    """, (username,))
                    row = cur.fetchone()
        except Exception as e:
            return Response({"detail": f"DB error: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not row:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

        user_id, password_hash, is_active = row

        if not is_active:
            return Response({"detail": "User is inactive."}, status=status.HTTP_401_UNAUTHORIZED)

        if not password_hash:
            return Response({"detail": "Password not set."}, status=status.HTTP_401_UNAUTHORIZED)

        # --- Verify bcrypt password ---
        try:
            valid = bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except ValueError:
            return Response({"detail": "Stored password hash format is invalid."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not valid:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

        # --- Issue JWT via SimpleJWT ---
        # Use a lightweight stub object so SimpleJWT can attach user_id claim correctly
        UserStub = type("UserStub", (), {"id": user_id, "pk": user_id, "is_active": is_active, "username": username})
        refresh = RefreshToken.for_user(UserStub())
        access = refresh.access_token
        # Optional custom claims:
        access["username"] = username

        return Response({
            "access": str(access),
            "refresh": str(refresh),
            "user": {"id": user_id, "username": username}
        }, status=status.HTTP_200_OK)
    

api_view(["GET"])
def get_collection_feedback_counts(request):
    try:
        with connection.cursor() as cursor:
            # Aggregate feedback counts per collection_name
            cursor.execute("""
                SELECT collection_name, feedback, COUNT(*) AS feedback_count
                FROM chatbot_logs
                GROUP BY collection_name, feedback
                ORDER BY collection_name, feedback;
            """)
            rows = cursor.fetchall()

        # Process results into a dictionary for easier frontend consumption
        data = {}
        for row in rows:
            collection_name, feedback, count = row
            if collection_name not in data:
                data[collection_name] = {}
            data[collection_name][feedback] = count

        return JsonResponse({"collection_feedback": data})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# views.py
@api_view(["GET"])
def get_chatbot_logs_with_collection(request):
    collection_filter = request.GET.get("collection_name")
    feedback_filter = request.GET.get("feedback")

    try:
        with connection.cursor() as cursor:
            base_query = """
                SELECT question, answer, feedback, query_time, domain, collection_name
                FROM chatbot_logs
                WHERE question != 'warmup'
            """

            filters = []
            params = []

            if collection_filter:
                filters.append("collection_name = %s")
                params.append(collection_filter)
            if feedback_filter:
                filters.append("feedback = %s")
                params.append(feedback_filter)

            if filters:
                base_query += " AND " + " AND ".join(filters)

            base_query += " ORDER BY query_time DESC"
            cursor.execute(base_query, params)
            rows = cursor.fetchall()

        logs = []
        for row in rows:
            logs.append({
                "id": str(uuid.uuid4()),
                "question": row[0],
                "answer": row[1],
                "feedback": row[2],
                "timestamp": row[3].strftime("%Y-%m-%d %H:%M:%S"),
                "domain": f"{row[4]}s",
                "collection_name": row[5]
            })

        return JsonResponse({"logs": logs})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

import numpy as np


def l2_normalize(vectors):
    """L2-normalize a list/array of vectors and return as Python lists."""
    arr = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True) + 1e-12
    return (arr / norms).tolist()

class UploadQAView(APIView):
    def post(self, request):
        # pdf_file = request.FILES.get('file')
        # collection_name = request.POST.get("collection_name")

        # if not pdf_file:
        #     return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)
        # if not collection_name:
        #     return Response({"error": "Missing collection_name"}, status=status.HTTP_400_BAD_REQUEST)

        # # Sanitize collection name to prevent SQL injection
        # if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', collection_name):
        #     return Response({"error": "Invalid collection_name. Use only alphanumeric and underscore."},
        #                     status=status.HTTP_400_BAD_REQUEST)

        # table_name = f"chatbot_{collection_name}"

        # try:
        #     # ---- Read PDF text ----
        #     doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
        #     text = "\n".join([page.get_text().replace('\x00', '') for page in doc])

        #     # ---- Regex: capture Q and A ----
        #     qa_pattern = re.compile(r'(?s)Q:\s*(.*?)\s*A:\s*(.*?)(?=\n\s*Q:|$)')
        #     matches = re.findall(qa_pattern, text)

        #     def clean_listnums(s: str) -> str:
        #         """Remove '1. ' or '2. ' style prefixes from text lines."""
        #         return re.sub(r'^\s*\d+\.\s*', '', s, flags=re.MULTILINE)

        #     def extract_links(answer_block: str):
        #         """
        #         Return (answer_without_links, list_of_urls).
        #         Keeps the answer text clean for embedding, but extracts URLs for display.
        #         """
        #         # Split on "Link:" or "Source:" markers
        #         parts = re.split(r'\n\s*(?:Link|Links?|Source|Sources?)\s*[:\-]\s*',
        #                          answer_block, maxsplit=1, flags=re.IGNORECASE)
        #         main = parts[0]
        #         tail = parts[1] if len(parts) > 1 else ""

        #         # Collect explicit URLs from tail
        #         urls = [u.strip() for u in re.findall(r'https?://\S+|www\.\S+', tail) if u.strip()]

        #         # Collect inline URLs in the whole block (dedupe)
        #         inline_urls = [u.strip() for u in re.findall(r'https?://\S+|www\.\S+', answer_block) if u.strip()]
        #         for u in inline_urls:
        #             if u not in urls:
        #                 urls.append(u)

        #         # Remove URLs from the embedding text
        #         main_no_urls = re.sub(r'https?://\S+|www\.\S+', '', main)

        #         return main_no_urls.strip(), urls

        #     display_chunks = []     # Stored in DB (with links)
        #     embed_questions = []    # <-- ONLY QUESTIONS go into embeddings

        #     for q, a in matches:
        #         q = clean_listnums(q).replace('\x00', '').strip()
        #         a = clean_listnums(a).replace('\x00', '').strip()
        #         if not (q and a):
        #             continue

        #         a_no_link, urls = extract_links(a)

        #         # --- Display text (full Q + cleaned A + URLs) ---
        #         display = f"Q: {q}\nA: {a_no_link}"
        #         if urls:
        #             for u in urls:
        #                 display += f"\n{u}"   # keep links visible (no "Link 1:" label)

        #         # --- Embedding text: QUESTION ONLY ---
        #         embed_questions.append(q)   # <-- key change

        #         display_chunks.append(display)

        #     if not embed_questions:
        #         return Response({"message": "No Q&A pairs found in the document"},
        #                         status=status.HTTP_204_NO_CONTENT)

        #     # ---- Generate embeddings ONLY from questions ----
        #     try:
        #         embeddings = model.encode(embed_questions)   # SentenceTransformer
        #         embeddings = l2_normalize(embeddings)
        #     except Exception as e:
        #         return Response({"error": f"Embedding error: {str(e)}"},
        #                         status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        #     # ---- Store to Postgres ----
        #     conn = psycopg2.connect(**DB_CONFIG)
        #     cursor = conn.cursor()

        #     cursor.execute(f"""
        #         CREATE TABLE IF NOT EXISTS {table_name} (
        #             id UUID PRIMARY KEY,
        #             text TEXT,
        #             vector FLOAT8[]
        #         );
        #     """)

        #     for display_chunk, vec in zip(display_chunks, embeddings):
        #         safe_text = display_chunk.replace('\x00', '')
        #         cursor.execute(
        #             f"""INSERT INTO {table_name} (id, text, vector) VALUES (%s, %s, %s)""",
        #             (str(uuid.uuid4()), safe_text, vec)
        #         )

        #     conn.commit()
        #     cursor.close()
        #     conn.close()

        #     return Response(
        #         {"message": f"{len(display_chunks)} Q&A chunks embedded (question-only) and stored in '{table_name}'."},
        #         status=status.HTTP_201_CREATED
        #     )

        # except Exception as e:
        #     return Response({"error": f"Internal Server Error: {str(e)}"},
        #                     status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        pdf_file = request.FILES.get('file')
        collection_name = request.POST.get("collection_name")

        if not pdf_file:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)
        if not collection_name:
            return Response({"error": "Missing collection_name"}, status=status.HTTP_400_BAD_REQUEST)

        # Sanitize collection name to prevent SQL injection
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', collection_name):
            return Response({"error": "Invalid collection_name. Use only alphanumeric and underscore."},
                            status=status.HTTP_400_BAD_REQUEST)

        table_name = f"chatbot_{collection_name}"

        try:
            # ---- Read PDF text ----
            doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
            text = "\n".join([page.get_text().replace('\x00', '') for page in doc])

            # ---- Regex: capture Q and A ----
            qa_pattern = re.compile(r'(?s)Q:\s*(.*?)\s*A:\s*(.*?)(?=\n\s*Q:|$)')
            matches = re.findall(qa_pattern, text)

            def clean_listnums(s: str) -> str:
                """Remove '1. ' or '2. ' style prefixes from text lines."""
                return re.sub(r'^\s*\d+\.\s*', '', s, flags=re.MULTILINE)

            def extract_links(answer_block: str):
                """
                Return (answer_without_links, list_of_urls).
                Keeps the answer text clean for embedding, but extracts URLs for display.
                """
                # Split on "Link:" or "Source:" markers
                parts = re.split(r'\n\s*(?:Link|Links?|Source|Sources?)\s*[:\-]\s*',
                                 answer_block, maxsplit=1, flags=re.IGNORECASE)
                main = parts[0]
                tail = parts[1] if len(parts) > 1 else ""

                # Collect explicit URLs from tail
                urls = [u.strip() for u in re.findall(r'https?://\S+|www\.\S+', tail) if u.strip()]

                # Collect inline URLs in the whole block
                inline_urls = [u.strip() for u in re.findall(r'https?://\S+|www\.\S+', answer_block) if u.strip()]
                for u in inline_urls:
                    if u not in urls:
                        urls.append(u)

                # Remove URLs from the embedding text
                main_no_urls = re.sub(r'https?://\S+|www\.\S+', '', main)

                return main_no_urls.strip(), urls

            display_chunks = []   # Stored in DB (with links)
            embed_chunks = []     # Used for embeddings only
            for q, a in matches:
                q = clean_listnums(q).replace('\x00', '').strip()
                a = clean_listnums(a).replace('\x00', '').strip() if a else "Please ask within scope of the website"
                print("====",a)
                if not (q and a):
                    continue

                a_no_link, urls = extract_links(a)

                # --- Display text (with URLs) ---
                display = f"Q: {q}\nA: {a_no_link}"
                if urls:
                    for u in urls:
                        display += f"\n{u}"   # exactly how you wanted (no "Link 1:" label)

                # --- Embedding text (no URLs) ---
                embed = f"Q: {q}\nA: {a_no_link}"

                display_chunks.append(display)
                embed_chunks.append(embed)

            if not embed_chunks:
                return Response({"message": "No Q&A pairs found in the document"},
                                status=status.HTTP_204_NO_CONTENT)

            # ---- Generate embeddings ----
            try:
                embeddings = model.encode(embed_chunks)   # your SentenceTransformer model
                embeddings = l2_normalize(embeddings)
            except Exception as e:
                return Response({"error": f"Embedding error: {str(e)}"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # ---- Store to Postgres ----
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id UUID PRIMARY KEY,
                    text TEXT,
                    vector FLOAT8[]
                );
            """)

            for display_chunk, vec in zip(display_chunks, embeddings):
                safe_text = display_chunk.replace('\x00', '')
                cursor.execute(
                    f"""INSERT INTO {table_name} (id, text, vector) VALUES (%s, %s, %s)""",
                    (str(uuid.uuid4()), safe_text, vec)
                )

            conn.commit()
            cursor.close()
            conn.close()

            return Response(
                {"message": f"{len(display_chunks)} Q&A chunks embedded and stored in '{table_name}'."},
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            return Response({"error": f"Internal Server Error: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)



from psycopg2 import sql


# class searchview(APIView):
#     def get(self, request):
#         collection = (request.query_params.get("collection_name") or "").strip()
#         q = (request.query_params.get("q") or "").strip()

#         # Required params; never dump rows if query empty
#         if not collection:
#             return Response({"error": "Missing collection_name"}, status=status.HTTP_400_BAD_REQUEST)
#         if not q:
#             return Response({"data": []}, status=status.HTTP_200_OK)

#         # Normalize to your per-collection table: asdc6 -> chatbot_asdc6
#         table = collection if collection.startswith("chatbot_") else f"chatbot_{collection}"

#         # Only allow safe table identifiers
#         if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
#             return Response({"error": "Invalid collection_name"}, status=status.HTTP_400_BAD_REQUEST)

#         # Default LIMIT=5 to match your pgAdmin query
#         try:
#             limit = int(request.query_params.get("limit", 5))
#         except ValueError:
#             limit = 5
#         limit = max(1, min(limit, 100))

#         # Build: SELECT id, text FROM public.chatbot_asdc6 WHERE text ILIKE '%q%' ORDER BY id DESC LIMIT
#         query = sql.SQL("""
#             SELECT id, text
#             FROM {schema}.{tbl}
#             WHERE {col} ILIKE %s
#             ORDER BY id DESC
#             LIMIT %s
#         """).format(
#             schema=sql.Identifier('public'),          # qualify schema to match pgAdmin
#             tbl=sql.Identifier(table),
#             col=sql.Identifier('text')
#         )
#         params = [f"%{q}%", limit]

#         try:
#             with connection.cursor() as cur:
#                 cur.execute(query, params)
#                 rows = cur.fetchall()

#             data = [{"id": r[0], "text": r[1]} for r in rows]
#             return Response({"data": data}, status=status.HTTP_200_OK)

#         except Exception as e:
#             return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class searchview(APIView):
    def get(self, request):
        collection = (request.query_params.get("collection_name") or "").strip()
        q = (request.query_params.get("q") or "").strip()

        # Required params; never dump rows if query empty
        if not collection:
            return Response({"error": "Missing collection_name"}, status=status.HTTP_400_BAD_REQUEST)
        if not q:
            return Response({"data": []}, status=status.HTTP_200_OK)

        # Normalize to your per-collection table: asdc6 -> chatbot_asdc6
        table = collection if collection.startswith("chatbot_") else f"chatbot_{collection}"

        # Only allow safe table identifiers
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            return Response({"error": "Invalid collection name. Use only alphanumeric and underscore."},
                            status=status.HTTP_400_BAD_REQUEST)

        # LIMIT
        try:
            limit = int(request.query_params.get("limit", 5))
        except ValueError:
            limit = 5
        limit = max(1, min(limit, 100))

        from django.db import connection
        try:
            with connection.cursor() as cur:
                # 1) Ensure table exists (public.table)
                cur.execute("SELECT to_regclass(%s)", [f"public.{table}"])
                reg = cur.fetchone()
                if not reg or reg[0] is None:
                    return Response(
                        {"error": f"Table public.{table} not found. (Check collection_name)"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # 2) Check if pg_trgm is available
                cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
                has_trgm = bool(cur.fetchone())

                params = [f"%{q}%", limit]

                if has_trgm:
                    # Use similarity() for ranking
                    sql_str = f"""
                        SELECT id, text
                        FROM public.{table}
                        WHERE text ILIKE %s
                        OR similarity(text::text, %s) > 0.3
                        ORDER BY similarity(text::text, %s) DESC
                        LIMIT %s
                    """
                    params = [f"%{q}%", q, q, limit]
                else:
                    # Fallback without pg_trgm (no similarity function)
                    sql_str = f"""
                        SELECT id, text
                        FROM public.{table}
                        WHERE text ILIKE %s
                        ORDER BY id DESC
                        LIMIT %s
                    """
                    # params already [f"%{q}%", limit]

                cur.execute(sql_str, params)
                rows = cur.fetchall()

            data = [{"id": r[0], "text": r[1]} for r in rows]
            return Response({"data": data}, status=status.HTTP_200_OK)

        except Exception as e:
            msg = str(e)
            # Add a helpful hint if similarity() or % operator fails
            if "similarity" in msg or "pg_trgm" in msg:
                msg += " (Hint: enable pg_trgm: CREATE EXTENSION IF NOT EXISTS pg_trgm;)"
            return Response({"error": msg}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
class AskPDFAPIwiththinkingView(APIView):
    ALIAS_MAP = {
        "cms": "candidate management system",
        "ETC": "Empowered Tech Committee",
        "appln": "application",
        "asdc": "Army Software Development Centre"
    }

    def expand_query(self, query):
        words = query.lower().split()
        expanded = " ".join([self.ALIAS_MAP.get(w, w) for w in words])
        if "how to login" in expanded or "login" in expanded:
            expanded += " in candidate management system"
        return expanded

    # Method to log question data into the PostgreSQL database
    def log_question_to_db(self, request, question, expanded_query, answer, link=None, duration=0.0, scores=None, feedback=None,collection_name=None):
        # print("-- Logging to DB")

        # Establish a connection to PostgreSQL
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # Prepare the data
        query_time = datetime.now()
        similarity_scores = json.dumps(scores) if scores else None

        ip_address = request.META.get('REMOTE_ADDR')
        domain = request.get_host()
        computer_name = socket.gethostname()

        # Insert the log data into the database
        cursor.execute("""
        INSERT INTO chatbot_logs (
            question, expanded_query, answer, link, query_time,
            similarity_scores, feedback,
            domain, ip_address, computer_name,collection_name
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        question, expanded_query, answer, link, query_time,
        similarity_scores, feedback,
        domain, ip_address, computer_name,collection_name
    ))

        conn.commit()
        cursor.close()
        conn.close()

        # print("-- Log inserted into DB")
    
    def update_feedback_in_db(self, question, feedback_type):
        print(f"Updating feedback for question: {question} with feedback type: {feedback_type}")
        # Establish a connection to PostgreSQL
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # Update the feedback in the database for the given question
        cursor.execute("""
            UPDATE chatbot_logs
            SET feedback = %s
            WHERE question = %s
        """, (feedback_type, question))

        # Commit the transaction
        conn.commit()

        # Close the connection
        cursor.close()
        conn.close()
        print(f"Feedback '{feedback_type}' updated for question: {question}")

    def post(self, request):
        question = request.data.get("query")
        feedback_type = request.data.get("feedback")
        collection_name = request.data.get("collection_name")
        if not collection_name:
            return Response({"error": "Missing 'collection_name' in request"}, status=status.HTTP_400_BAD_REQUEST)


        if not question:
            return Response({"error": "Missing 'query' in request"}, status=status.HTTP_400_BAD_REQUEST)

        expanded_query = self.expand_query(question)
        results, duration = processor.searchwiththinking(expanded_query,collection_name)

        scores = [r["score"] for r in results]
        if not results:
            self.log_question_to_db(
            request=request,
            question=question,
            expanded_query=expanded_query,
            answer="Please ask a question within the scope of the website.",
            link=None,
            duration=duration,
            scores=scores,
            feedback='dislike',
            collection_name=collection_name
        )
            return Response({
                "context": [],
                "answer": "Please ask a question within the scope of the website.",
                "link": None,
                "duration": duration,
                "scores": scores
            })

        context_chunks = [r["text"] for r in results]
        answer = ""
        link = None

        for chunk in context_chunks:
            if "A:" in chunk:
                answer = chunk.split("A:", 1)[-1].strip()
            
            # Check if the chunk contains a link
            # Regex to find any URL starting with http or https
            found_links = re.findall(r'https?://[^\s]+', chunk)
            if found_links:
                link = found_links[0] # Take the first link found


        answer = answer.replace("Link :", "").replace("Link:-", "").replace("Link:", "").strip()
        if link:
            answer = answer.replace(link, "").strip()
            link = f'<a href="{link}" target="_blank">{link}</a>'

        # Log the question and answer data to PostgreSQL database
        self.log_question_to_db(request, question, expanded_query, answer, link, duration, scores, feedback_type,collection_name)

        # Handle feedback (like/dislike)
        if feedback_type:
            print(f"Received feedback: {feedback_type} for question: {question}")   
            if feedback_type not in ["like", "dislike"]:
                return Response({"error": "Invalid feedback type"}, status=status.HTTP_400_BAD_REQUEST)
            # You can add feedback logic here (update the feedback in DB if needed)
            # For now, feedback will be logged with the question as part of the original insert.
            self.update_feedback_in_db(question, feedback_type)

        return Response({
            "context": context_chunks,
            "answer": answer,
            "link": link,
            "duration": duration,
            "scores": scores
        })


@api_view(['POST'])
def add_chunk(request):
    if request.method == 'POST':
        # Extract data from the request
        collection_name = request.data.get('collection_name')
        text = request.data.get('text')

        # Validate the input data
        if not collection_name or not text:
            return Response({'detail': 'Missing required fields: collection_name or text'}, status=status.HTTP_400_BAD_REQUEST)

        # Step 1: Generate the vector using 'all-mini-v2l6' model
        sentence_model = SentenceModel()  # Create an instance
        vector = sentence_model.encode(text) 
        # Convert the vector to binary format (PostgreSQL BYTEA)
        vector_binary =  vector.tolist()

        # Step 2: Insert the chunk into PostgreSQL using raw SQL
        with connection.cursor() as cursor:
            cursor.execute(f"""INSERT INTO chatbot_{collection_name} (id, text, vector) VALUES (%s, %s, %s)""",
 [str(uuid.uuid4()), text, vector_binary])  # Adjust table name as needed

        # Return success response
        return Response({'detail': 'Chunk added successfully with generated vector'}, status=status.HTTP_201_CREATED)
    
@api_view(['POST'])
def delete_collection(request):
    """
    API view to delete the entire collection (all records) from both:
    1. `uploaded_pdfs` table
    2. The dynamically created chatbot table based on the collection name
    """
    if request.method == 'POST':
        # Extract collection_name from request
        collection_name = request.data.get('collection_name')

        if not collection_name:
            return Response({"error": "Missing collection_name"}, status=status.HTTP_400_BAD_REQUEST)

        # Sanitize collection name to prevent SQL injection
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', collection_name):
            return Response({"error": "Invalid collection_name. Use only alphanumeric and underscore."},
                             status=status.HTTP_400_BAD_REQUEST)

        table_name = f"chatbot_{collection_name}"

        try:
            # Initialize the database connection
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            # Step 1: Delete records from uploaded_pdfs where collection_name matches
            cursor.execute(f"DELETE FROM uploaded_pdfs WHERE collection_name = %s;", [collection_name])
            
            # Step 2: Delete records from chatbot_{collection_name} table
            cursor.execute(f"DROP TABLE IF EXISTS {table_name};")

            # Optional: Drop the table entirely if you want to remove the collection
            # cursor.execute(f"DROP TABLE IF EXISTS {table_name};")

            # Commit the transaction
            conn.commit()

            # Check if any rows were deleted
            if cursor.rowcount > 0:
                message = f"Successfully deleted records from {table_name} and uploaded_pdfs for collection '{collection_name}'."
                return Response({"message": message}, status=status.HTTP_200_OK)
            else:
                return Response({"error": f"No records found for collection '{collection_name}' to delete."}, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            # Handle errors like connection issues or invalid SQL syntax
            return Response({"error": f"Internal Server Error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        finally:
            # Close database connection
            cursor.close()
            conn.close()


@api_view(['POST'])
def edit_chunk(request, collection_name, uuid):
        """
        Edit a Q&A chunk.
        Expects request.data['text'] as a single string:
            "Q: question here\nA: answer here"
        """

        # Extract the text string from request
        text_data = request.data.get('text', '')  # default to empty string

        if not text_data or not isinstance(text_data, str):
            return Response(
                {"error": "Invalid text format. Must be a string with Q: and A:."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Parse question and answer from string
        parts = text_data.split('\nA:', 1)  # split only at first occurrence
        question = parts[0].replace('Q:', '').strip() if parts[0] else ''
        answer = parts[1].strip() if len(parts) > 1 else ''

        if not question and not answer:
            return Response(
                {"error": "At least one of 'Q' or 'A' must be provided."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Combine Q and A in proper format for storage
        combined_text = f"Q: {question}\nA: {answer}"

        # table_name = collection_name

        # Prepare raw SQL query
        update_query = f"""
            UPDATE {collection_name}
            SET text = %s
            WHERE id = %s
        """
        query_params = [combined_text, uuid]

        print("Update Query:", update_query, combined_text)

        try:
            with connection.cursor() as cursor:
                cursor.execute(update_query, query_params)
                connection.commit()

            return Response({"message": "Chunk updated successfully"}, status=status.HTTP_200_OK)
        
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



from rest_framework.parsers import MultiPartParser, FormParser

QA_RE = re.compile(r'(?s)Q:\s*(.*?)\s*A:\s*(.*?)(?=\n\s*Q:|$)')

def clean_listnums(s: str) -> str:
    return re.sub(r'^\s*\d+\.\s*', '', s, flags=re.MULTILINE)

def extract_links(answer_block: str):
    parts = re.split(r'\n\s*(?:Link|Links?|Source|Sources?)\s*[:\-]\s*',
                     answer_block, maxsplit=1, flags=re.IGNORECASE)
    main = parts[0]
    tail = parts[1] if len(parts) > 1 else ""
    urls = [u.strip() for u in re.findall(r'https?://\S+|www\.\S+', tail) if u.strip()]
    inline_urls = [u.strip() for u in re.findall(r'https?://\S+|www\.\S+', answer_block) if u.strip()]
    for u in inline_urls:
        if u not in urls:
            urls.append(u)
    main_no_urls = re.sub(r'https?://\S+|www\.\S+', '', main)
    return main_no_urls.strip(), urls

def extract_text_from_pdf_bytes(b: bytes) -> str:
    # uses PyMuPDF (fitz)
    doc = fitz.open(stream=b, filetype="pdf")
    pages = []
    for p in doc:
        try:
            pages.append(p.get_text().replace('\x00', ''))
        except Exception:
            pages.append("")
    return "\n".join(pages).strip()

class UploadQApatchView(APIView):
    """
    POST /api/collections/<collection_name>/upload/
      - multipart/form-data with key 'file' (PDF)
      - optional form fields: chunk_size, overlap (not used here)
    """
    parser_classes = [MultiPartParser, FormParser]

    def _validate_collection(self, name: str) -> bool:
        return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name))

    def post(self, request, collection_name):
        # basic validation
        if not collection_name:
            return Response({"error": "Missing collection_name in URL"}, status=status.HTTP_400_BAD_REQUEST)
        if not self._validate_collection(collection_name):
            return Response({"error": "Invalid collection_name. Use only alphanumeric and underscore."},
                            status=status.HTTP_400_BAD_REQUEST)

        pdf_file = request.FILES.get('file')
        if not pdf_file:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        # Read PDF bytes
        try:
            pdf_bytes = pdf_file.read()
        except Exception as e:
            return Response({"error": f"Failed reading uploaded file: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        # Extract text
        try:
            text = extract_text_from_pdf_bytes(pdf_bytes)
        except Exception as e:
            return Response({"error": f"Failed to extract text from PDF: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        # Find Q/A pairs
        matches = re.findall(QA_RE, text)
        display_chunks = []
        embed_questions = []

        for q, a in matches:
            q = clean_listnums(q).replace('\x00', '').strip()
            a = clean_listnums(a).replace('\x00', '').strip()
            if not (q and a):
                continue
            a_no_link, urls = extract_links(a)
            display = f"Q: {q}\nA: {a_no_link}"
            if urls:
                for u in urls:
                    display += f"\n{u}"
            display_chunks.append(display)
            embed_questions.append(q)

        if not embed_questions:
            return Response({"message": "No Q&A pairs found in the PDF"}, status=status.HTTP_204_NO_CONTENT)

        # generate embeddings (expects model + l2_normalize available)
        try:
            embeddings = model.encode(embed_questions)   # list/ndarray of vectors
            embeddings = l2_normalize(embeddings)
        except Exception as e:
            return Response({"error": f"Embedding error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Persist to Postgres - use psycopg2.sql to safely insert table identifier
        table_name = f"chatbot_{collection_name}"
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            # create table if not exists using Identifier
            cursor.execute(
                sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {table} (
                        id UUID PRIMARY KEY,
                        text TEXT,
                        vector FLOAT8[]
                    );
                """).format(table=sql.Identifier(table_name))
            )

            insert_sql = sql.SQL("""
                INSERT INTO {table} (id, text, vector) VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET text = EXCLUDED.text, vector = EXCLUDED.vector
            """).format(table=sql.Identifier(table_name))

            inserted_ids = []
            for display_text, vec in zip(display_chunks, embeddings):
                rid = str(uuid.uuid4())
                safe_text = display_text.replace('\x00', '')
                # Ensure vec is a plain python list of floats
                try:
                    vec_list = list(map(float, vec.tolist())) if hasattr(vec, "tolist") else list(map(float, vec))
                except Exception:
                    # as fallback try casting directly
                    vec_list = list(map(float, vec))
                cursor.execute(insert_sql, (rid, safe_text, vec_list))
                inserted_ids.append(rid)

            conn.commit()
            cursor.close()
            conn.close()

            return Response(
                {"message": f"{len(inserted_ids)} Q&A chunks stored", "inserted_ids": inserted_ids},
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            # best effort cleanup
            try:
                conn.rollback()
                cursor.close()
                conn.close()
            except Exception:
                pass
            return Response({"error": f"DB error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)




class DeleteChatbotLogAPIView(APIView):
    """
    DELETE /api/logs/<id>/ - delete a chatbot log by ID
    """

    def delete(self, request, id):
        # print("Deleting log with ID:", id)
        try:
            with connection.cursor() as cursor:
                delete_query = """
                    DELETE FROM chatbot_logs
                    WHERE id = %s
                    RETURNING id
                """
                # print("Executing query:", delete_query, id)
                cursor.execute(delete_query, [str(id)])  # convert UUID to string
                deleted_row = cursor.fetchone()

                if not deleted_row:
                    return Response({"message": "Log not found"}, status=404)

            return Response({"message": "Log deleted successfully", "deleted_id": deleted_row[0]}, status=200)

        except Exception as e:
            return Response({"message": "Error deleting log", "error": str(e)}, status=500)
        

@api_view(["POST"])
def mark_chatbot_log_complete(request, id):
    """
    PATCH /api/chatbot/mark-complete/<log_id>/
    Sets is_complete = TRUE for the given log ID.
    """
    try:
        with connection.cursor() as cursor:
            update_query = """
                UPDATE chatbot_logs
                SET is_complete = TRUE
                WHERE id = %s
                RETURNING id;
            """
            cursor.execute(update_query, [id])
            updated = cursor.fetchone()

        if not updated:
            return JsonResponse({"message": "No record found for the given ID."}, status=404)

        return JsonResponse({
            "message": "Record marked as complete successfully.",
            "updated_id": updated[0]
        }, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
