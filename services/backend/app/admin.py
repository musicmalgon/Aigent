from sqladmin import ModelView

from app.models.user import User


class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.email, User.user_type, User.created_at]
    column_searchable_list = [User.email]