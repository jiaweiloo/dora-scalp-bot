import os
import urllib

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
DATABASE_USERNAME = os.getenv('DATABASE_USERNAME')
DATABASE_PASSWORD = os.getenv('DATABASE_PASSWORD')


class DALUtils:
    db = None
    session = None

    def __init__(self):
        if self.db is None:
            self.db = create_engine(
                f"postgresql://{DATABASE_USERNAME}:{urllib.parse.quote_plus(DATABASE_PASSWORD)}@{DATABASE_URL}")
            Session = sessionmaker(self.db)
            self.session = Session()
            self.session.autoflush = True


