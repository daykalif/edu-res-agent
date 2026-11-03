from fastapi import FastAPI
from app.database import Base, engine
from app.api.auth import router as auth_router

# 根据模型创建数据库表。
Base.metadata.create_all(bind=engine)

app = FastAPI()

app.include_router(auth_router)


@app.get("/")
def root():
    return {"message": "Hello FastAPI"}
