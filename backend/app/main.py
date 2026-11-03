from fastapi import FastAPI
from app.database import Base, engine
from app.api import api

# 根据模型创建数据库表。
Base.metadata.create_all(bind=engine)

app = FastAPI()

# 注册路由
app.include_router(api)


@app.get("/")
def root():
    return {"message": "Hello FastAPI"}
