# Django settings for production use

from settings import *

DEBUG=False
TEMPLATE_DEBUG=DEBUG

STATIC_ROOT="{{project_directory}}/static"

TILLWEB_DATABASE=sessionmaker(bind=create_engine(
        'postgresql+psycopg2:///{}'.format(
            quicktill_database),pool_recycle=600))
