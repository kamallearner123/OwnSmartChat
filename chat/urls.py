from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('api/chat/', views.chat_api, name='chat_api'),
    path('api/stats/', views.stats_api, name='stats_api'),
    path('api/history/', views.history_api, name='history_api'),
    path('api/scrape/', views.scrape_api, name='scrape_api'),
    path('api/pdf/', views.pdf_api, name='pdf_api'),
]
