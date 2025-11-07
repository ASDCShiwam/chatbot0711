"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from api import views
from django.views.generic import TemplateView
# from api import asdcviews
from api import postgres_views
from django.conf import settings
from django.conf.urls.static import static
urlpatterns = [
    path('admin/', admin.site.urls),
    path('chatbot/Pdfmanager/', TemplateView.as_view(template_name="fileindexing.html"), name='PDFmanager'),
    path('chatbot/analytics/', TemplateView.as_view(template_name="fileindexing.html"), name='fileindexing'),
    path('chatbot/dashboard/', TemplateView.as_view(template_name="dashboard.html"), name='dashboard'),
    path('chatbot/login/', TemplateView.as_view(template_name="login.html"), name='login'),
    # path('chatbot/login/', TemplateView.as_view(template_name="login.html"), name='login'),
    path('chatbot/bot/', TemplateView.as_view(template_name="index.html"), name='index'),
    path("chatbot/ask/", views.AskPDFAPIView.as_view(), name="ask_query"),
    # path('chatbot/loginapi/', postgres_views.RawLoginNoSerializerAPIView.as_view(), name='login'),
    path('chatbot/asdcask/', postgres_views.AskPDFAPIView.as_view(), name='asdc_ask_query'),
    path('chatbot/asdcfeedback/', postgres_views.FeedbackUpdateAPIView.as_view(), name='asdc_feedback'),
    # path('api/asdcingest-pdf/', asdcviews.IngestPDFAPIView.as_view(), name='asdc_ingest_pdf'),
    path('chatbot/ingest-pdf/', postgres_views.UploadQAView.as_view(), name='upload_pdf'),
    path("chatbot/store-pdf/", postgres_views.PDFStoreAPIView.as_view(), name="store_pdf"),
    path('chatbot/files-by-collection/<str:collection_name>/', postgres_views.FilesByCollectionAPIView.as_view()),
    path("chatbot/get_chunks/", postgres_views.CollectionDataView.as_view(), name="get_chunks"),
    path("chatbot/delete-chunk/<str:collection_name>/<uuid:id>/", postgres_views.DeleteChunkView.as_view(), name="delete_chunk"),
    path("chatbot/query-logs/", postgres_views.get_chatbot_logs_raw, name="delete_chunk"),
    path("chatbot/domains/", postgres_views.DomainListView.as_view(), name="delete_chunk"),
    path("chatbot/logs/", postgres_views.DomainLogView.as_view(), name="delete_chunk"),
    path("chatbot/collection-feedback/", postgres_views.get_collection_feedback_counts, name="delete_chunk"),
    path("chatbot/chatbot-logs/", postgres_views.get_chatbot_logs_with_collection, name="delete_chunk"),
    path("chatbot/search/", postgres_views.searchview.as_view(), name="search"),
    path('chatbot/searchthinking/',postgres_views.AskPDFAPIwiththinkingView.as_view(), name='search-viewthinking'),
    path('chatbot/add-chunk/', postgres_views.add_chunk, name='add_chunk'),
    path('chatbot/delete-collection/', postgres_views.delete_collection, name='delete_collection'),  # DELETE request
    path('chatbot/edit_chunk/<str:collection_name>/<uuid:uuid>/', postgres_views.edit_chunk, name='edit_chunk'),
    path("chatbot/editcollections/<str:collection_name>/", postgres_views.UploadQApatchView.as_view(), name="collection-upsert"),
    path('chatbot/logs/<uuid:id>/', postgres_views.DeleteChatbotLogAPIView.as_view(), name='delete-log'),
    path('chatbot/mark-complete/<uuid:id>/', postgres_views.mark_chatbot_log_complete, name='mark_chatbot_log_complete'),
    path('chatbot/loginapi/', postgres_views.RawLoginNoSerializerAPIView.as_view(), name='LoginView'),
    path('chatbot/register/', views.RegisterView.as_view(), name='registerview'),
    
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
