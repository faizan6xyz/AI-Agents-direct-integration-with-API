import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlcipher3 import dbapi2 as sqlcipher
load_dotenv()
DB_PASSWORD = os.getenv("DB_PASSWORD")

def create_encrypted_connection():
    conn = sqlcipher.connect("new.db")
    conn.execute(f"PRAGMA key = '{DB_PASSWORD}'")
    return conn

engine = create_engine("sqlite://", creator=create_encrypted_connection)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)   # auto-increment PK (better than name as PK)
    name = Column(String, nullable=False)
    token = Column(String, nullable=False)

    def __repr__(self):
        return f"<User(id={self.id}, name='{self.name}', token='{self.token}')>"

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()
new_user = User(name="Faizan", token="abc123token")
session.add(new_user)
session.commit()
print("Encrypted database created and record inserted.")
users = session.query(User).all()
for u in users:
    print(u)

session.close()