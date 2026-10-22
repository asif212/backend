import pytest
from sqlalchemy import create_engine, select, func
from my_time.db import Base
from my_time.models.core import Team, User, Session as LoginSession
from my_time.models import core
from my_time.import_legacy import import_data


def test_import_preserves_ids_discards_sessions_and_refuses_overwrite(tmp_path):
    url = f"sqlite:///{tmp_path / 'source.db'}"
    source = create_engine(url)
    target = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    legacy_names={value.__tablename__ for value in vars(core).values()
                  if getattr(value,'__module__',None)==core.__name__ and hasattr(value,'__tablename__')}
    Base.metadata.create_all(source,tables=[table for table in Base.metadata.sorted_tables if table.name in legacy_names])
    Base.metadata.create_all(target)
    with source.begin() as db:
        db.execute(Team.__table__.insert(), {"id":7,"name":"Original"})
        db.execute(User.__table__.insert(), {"id":9,"team_id":7,"name":"Person","username":"person"})
        db.execute(LoginSession.__table__.insert(), {"id_hash":"old-session","user_id":9})
    counts = import_data(url, target)
    assert counts['users'] == 1
    with target.connect() as db:
        assert db.execute(select(User.id)).scalar() == 9
        assert db.execute(select(func.count()).select_from(LoginSession)).scalar() == 0
    with pytest.raises(ValueError, match="Destination must be empty"):
        import_data(url, target)
    source.dispose(); target.dispose()
