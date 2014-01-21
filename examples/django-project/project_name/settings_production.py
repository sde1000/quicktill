# Django settings for production use

from settings import *

DEBUG=False
TEMPLATE_DEBUG=DEBUG

# MEDIA_ROOT=

# MEDIA_URL=

# TEMPLATE_DIRS=()

# STATICFILES_DIRS=()

# STATIC_ROOT=""

TILLWEB_DATABASE=sessionmaker(bind=create_engine(
        'postgresql+psycopg2:///{}'.format(
            quicktill_database),pool_recycle=600))
