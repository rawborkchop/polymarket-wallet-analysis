# polymarket-wallet-analysis
 source venv/bin/activate && python manage.py runserver 0.0.0.0:8000
   source venv/bin/activate && celery -A polymarket_project worker --loglevel=info


  source venv/bin/activate
  python manage.py runserver 0.0.0.0:8000 > django_server.log 2>&1 &
  celery -A polymarket_project worker --loglevel=info > celery_worker.log 2>&1 &