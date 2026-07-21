from fastapi import FastAPI
from sqladmin import Admin
from app.core.database import Base, engine
from app.admin import UserAdmin
from app.models import user  # noqa: F401
from app.api import auth

app = FastAPI(title="Re:Mind API")

Base.metadata.create_all(bind=engine)

admin = Admin(app, engine)
admin.add_view(UserAdmin)

app.include_router(auth.router)


@app.get("/")
def health_check():
    return {"status": "ok"}