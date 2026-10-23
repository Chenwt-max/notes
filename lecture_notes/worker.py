import sys
from .resources import configure
from .settings import settings
config=settings()
configure(config['processing_mode'],config['cpu_threads'],config['device'])
from .pipeline import run_job

if __name__ == '__main__':
    run_job(sys.argv[1])
