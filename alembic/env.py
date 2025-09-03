import logging
from logging.config import fileConfig

from alembic import context

logger = logging.getLogger('alembic.env')

# 获取父目录的绝对路径
# parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# 将 models 目录添加到 sys.path 中
# models_dir = os.path.join(parent_dir, 'models')
# configs_dir = os.path.join(parent_dir, 'configs')
# sys.path.append(models_dir)
# sys.path.append(configs_dir)

# 导入模块
from models.base import Base
from models import engine

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def get_engine():
    return engine.engine


def get_engine_url():
    try:
        return get_engine().url.render_as_string(hide_password=False).replace(
            '%', '%%')
    except AttributeError:
        return str(get_engine().url).replace('%', '%%')


# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
config.set_main_option('sqlalchemy.url', get_engine_url())
# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
def get_metadata():
    base_metadata = Base.metadata
    print(f"metadata:{base_metadata}")
    return base_metadata

def include_object(object, name, type_, reflected, compare_to):
    print(f"include_object:{name}, {type_}, {reflected}, {compare_to}")
    logger.debug(f"include_object:{name}, {type_}, {reflected}, {compare_to}")
    if type_ == "index" and name.startswith("ix_"):
        return True
    if type_ == "index" and name.startswith("ag_"):
        return False
    if type_ == "table":
        schema = getattr(object, "schema", None)
        print(f"schema:{schema}, name:{name}, type_:{type_}")
        if schema in ("ag_catalog", "pg_jieba", "information_schema", "pg_catalog"):
            return False

        # 例子2：忽略掉某些特定表
    if type_ == "table" and name.startswith("ag_"):
        return False

    return True

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=get_metadata(), literal_binds=True
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, 'autogenerate', False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info('No changes in schema detected.')

    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            process_revision_directives=process_revision_directives,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    logger.debug('offline mode')
    run_migrations_offline()
else:
    logger.debug('online mode')
    run_migrations_online()
