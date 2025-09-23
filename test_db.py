import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
url = os.getenv("DATABASE_URL")
print("URL =", url)

engine = create_engine(url)
with engine.connect() as conn:
    print("Connected OK")
    print("Server date:", conn.execute(text("select current_date")).scalar())
