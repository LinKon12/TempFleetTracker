# database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base,sessionmaker


DATABASE_URL = "postgresql+psycopg2://postgres:root@localhost:5432/FleetTracker"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()