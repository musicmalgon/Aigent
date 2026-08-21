from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import settings
from app.core.database import Base
from app.models import persistence, user  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Enum(native_enum=False, create_constraint=True)로 만든 체크 제약(현재
# persistence_baseline_status, daily_record_source 둘뿐 -- app/models/persistence.py)은
# SQLAlchemy가 IN절을 POSTCOMPILE 바인드 파라미터로 만든다. 마이그레이션이
# DB에 구워 넣은 리터럴 SQL("status IN ('ready', 'insufficient')")과 모델
# 쪽에서 다시 렌더링한 미컴파일 표현("status IN (__[POSTCOMPILE_param_1])")을
# alembic이 문자열로 비교하면, 값이 완전히 같아도 매번 "다르다"고 오탐한다
# (SQLAlchemy/Alembic의 알려진 한계 -- Enum 체크 제약은 안정적으로 텍스트
# 비교가 안 됨). 이 둘의 유일한 출처는 여전히 모델의 Enum 정의이므로, 자동
# 생성 비교(`alembic check`, `alembic revision --autogenerate`)에서만 안전하게
# 제외한다 -- 실제 마이그레이션 적용/제약 자체에는 영향 없음.
ENUM_BACKED_CHECK_CONSTRAINTS = {"persistence_baseline_status", "daily_record_source"}


def include_object(object: object, name: str | None, type_: str, *_: object) -> bool:
    if type_ == "check_constraint" and name in ENUM_BACKED_CHECK_CONSTRAINTS:
        return False
    return True


def get_database_url() -> str:
    configured_url = config.get_main_option("sqlalchemy.url")
    return configured_url or settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_object=include_object,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
