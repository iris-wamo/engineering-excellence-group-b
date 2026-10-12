# SQLAlchemy Sync vs Async: Engines, Sessions, Lifecycle, and Connection Pooling

## 1. Purpose
This document researches SQLAlchemy synchronous and asynchronous database access, with a focus on:
- Sync vs async engines and sessions
- Complexity, benefits, and risks
- When each approach is appropriate
- Request-scoped session lifecycle
- Commit, rollback, and close behavior
- Consequences of failing to close sessions
- Connection pool configuration
- Production session/connection hygiene

The goal is research and engineering judgment, not an application-wide migration to asynchronous SQLAlchemy.

## 2. SQLAlchemy Architecture
A simplified SQLAlchemy architecture is:
```
Application
|
v
Session / AsyncSession
|
v
Engine / AsyncEngine
|
v
Connection Pool
|
v
DBAPI Driver
|
v
PostgreSQL / MySQL / etc.
```

The important distinction is that a `Session` is not itself a database connection.
The `Session` manages ORM state and transactions. When database work is required, it obtains a connection from the `Engine`'s connection pool.

SQLAlchemy describes the `Session` as the main interface for database operations and ORM object state. A transaction normally remains active until the `Session` commits, rolls back, or closes. [SQLAlchemy Session Basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)

## 3. Synchronous SQLAlchemy
A synchronous application normally uses:
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

engine = create_engine(DATABASE_URL)
with Session(engine) as session:
    result = session.execute(...)
    session.commit()
```

Typical components:
```
create_engine()
|
v
Engine
|
v
Session
|
v
synchronous DB driver
```

Examples of synchronous drivers include:
- PostgreSQL -> psycopg
- MySQL -> PyMySQL / mysqlclient

The important characteristic is that database I/O is synchronous.
When the application executes a database operation, the executing thread waits for the database operation to complete.

### Advantages
**Simplicity**
The programming model is straightforward:
```python
result = session.execute(statement)
```
rather than:
```python
result = await session.execute(statement)
```
There is less asynchronous-specific behavior to understand.

**Mature ecosystem**
Traditional SQLAlchemy ORM usage, synchronous libraries, scripts, CLI tools, migrations, and many background workloads work naturally with synchronous Sessions.

**Easier debugging**
The control flow is generally easier to follow because execution is sequential:
`call function | execute SQL | wait for DB | receive result | continue`

**Good fit for many APIs**
A synchronous database layer is not automatically a performance problem.
If the application's workload is moderate, and database calls are relatively short, synchronous SQLAlchemy can be a perfectly reasonable architecture.

## 4. Asynchronous SQLAlchemy
SQLAlchemy provides asyncio support through:
```python
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

engine = create_async_engine(DATABASE_URL)
SessionLocal = async_sessionmaker(engine)

async with SessionLocal() as session:
    result = await session.execute(...)
    await session.commit()
```

The architecture becomes:
```
Application / asyncio event loop
|
v
AsyncSession
|
v
AsyncEngine
|
v
Async-compatible driver
|
v
Database
```

SQLAlchemy's current documentation states that `AsyncSession` provides the ORM functionality through asyncio-compatible database drivers.

## 5. Why Async Exists
The main advantage of async database access is not that an individual SQL query becomes faster.
Instead, async allows the application to use its event loop while waiting for I/O.

For example:
```
Request A | |---- DB query --------------------| waiting
Request B |     |---- DB query --------| waiting
Request C |         |---- API request -----------------|
```

With asynchronous I/O, the application can perform other work while one operation is waiting for the database.

This can be valuable for applications with:
- High concurrent request volume
- Many I/O-bound operations
- Async HTTP APIs
- WebSockets
- Streaming
- Multiple external services
- Long-running I/O waits

## 6. Important Async Complexity
Async SQLAlchemy introduces additional rules that do not exist in quite the same way with normal synchronous ORM usage.

For example, implicit lazy-loading can cause problems because attribute access can unexpectedly require database I/O.
SQLAlchemy specifically warns that applications using `AsyncSession` need to avoid implicit I/O on attribute access and lazy-loaded relationships.

For example:
```python
user = await session.get(User, user_id)
print(user.orders)
```

If `orders` requires lazy loading, accessing the attribute may require database I/O.
With async SQLAlchemy, that I/O needs to be handled explicitly using supported async patterns.

This means developers need to understand:
- `await`
- AsyncSession lifecycle
- eager loading
- lazy loading restrictions
- expired attributes
- concurrent task/session boundaries
- async-compatible database drivers

## 7. AsyncSession Must Not Be Shared Across Concurrent Tasks
An important production rule is:
```
1 AsyncSession
|
+---- Task A
+---- Task B
+---- Task C
```
is unsafe.

Instead:
```
Task A -> AsyncSession A
Task B -> AsyncSession B
Task C -> AsyncSession C
```

SQLAlchemy explicitly documents `AsyncSession` as a mutable, stateful object representing a single database transaction and states that it should not be shared between concurrent asyncio tasks.

This is an important distinction from simply saying "async is better for concurrency."
Async gives concurrency opportunities, but session ownership must still be correct.

## 8. Sync vs Async Comparison

| Area | Sync SQLAlchemy | Async SQLAlchemy |
| :--- | :--- | :--- |
| **Session** | `Session` | `AsyncSession` |
| **Engine** | `Engine` | `AsyncEngine` |
| **Factory** | `sessionmaker` | `async_sessionmaker` |
| **Query** | `session.execute()` | `await session.execute()` |
| **Commit** | `session.commit()` | `await session.commit()` |
| **Rollback** | `session.rollback()` | `await session.rollback()` |
| **Close** | `session.close()` | `await session.close()` / `aclose()` |
| **Driver** | Sync DB driver | Async-compatible DB driver |
| **I/O model** | Blocking | Awaitable/non-blocking |
| **Complexity** | Lower | Higher |
| **Lazy loading**| Normal ORM behavior | Requires extra care |
| **Concurrent tasks** | Thread/session rules apply | Separate AsyncSession per task |
| **Best fit** | Simpler APIs, scripts, moderate workloads | Highly concurrent I/O-heavy services |

## 9. When Should We Use Sync?
Synchronous SQLAlchemy is a reasonable choice when:
- The application does not require very high I/O concurrency.
- Most database operations are short.
- The existing application is synchronous.
- The team values simpler database code.
- Most dependencies are synchronous.
- There is no demonstrated event-loop blocking problem.

A key engineering principle is:
*Do not migrate to async merely because async exists.*
Async introduces architectural complexity. The migration should be driven by an actual workload or architectural requirement.

## 10. When Should We Use Async?
Async SQLAlchemy is useful when:
- The application is already asyncio-based.
- There are many concurrent requests.
- Requests spend significant time waiting on I/O.
- The application uses async HTTP clients and other async services.
- WebSocket or streaming workloads are important.
- Blocking database operations are demonstrably affecting event-loop responsiveness.

The important point is that async helps primarily with concurrency and I/O utilization, not with making SQL itself execute faster.

## 11. Request-Scoped Session Pattern
A common web API pattern is:
```
HTTP Request
|
v
Create Session
|
v
Endpoint
|
+---- SELECT
|
+---- INSERT / UPDATE / DELETE
|
v
Commit or Rollback
|
v
Close Session
|
v
Return HTTP Response
```

The SQLAlchemy documentation recommends keeping the Session lifecycle separate from business/data-access functions and defining clear transaction boundaries. It also recommends keeping transactions short.

A typical dependency pattern looks like:
```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

The exact implementation in this project must be checked against:
`app/db/session.py`

## 12. Commit, Rollback, and Close Are Different
These operations have different responsibilities.

### Commit
`session.commit()`
means:
```
Flush pending ORM changes
|
v
COMMIT database transaction
|
v
Release transaction connection
```

SQLAlchemy documents that `commit()` flushes pending changes before committing the current transaction. After the transaction completes, the associated connection is released back to the Engine's pool.

Commit therefore means:
*Make the transaction's changes permanent.*

### Rollback
`session.rollback()`
means:
```
Current transaction
|
v
ROLLBACK
|
v
Discard uncommitted changes
|
v
Release connection
```

SQLAlchemy documents that rollback releases database connections associated with the transaction back to the connection pool.

Rollback is especially important after an exception.
For example:
```python
try:
    user.name = "Aqdas"
    session.commit()
except Exception:
    session.rollback()
    raise
```

Without the rollback, the Session can remain in an unusable/inactive transactional state after certain failures, particularly after a flush failure.

## 13. Close
`session.close()`
has a different purpose.

Close:
- releases transactional/connection resources
- expunges ORM objects
- returns connections to the pool
- resets the Session's state

SQLAlchemy explicitly recommends limiting Session scope and ensuring `Session.close()` is called, especially when commit/rollback are not otherwise used.

A context manager provides this automatically:
```python
with Session(engine) as session:
    result = session.execute(statement)
```

When the block ends:
`Session.close()`
is performed automatically.

## 14. Request Lifecycle
The desired lifecycle is:
```
HTTP Request
|
v
Create DB Session
|
v
Endpoint runs
|
+---------+---------+
|                   |
Success             Error
|                   |
v                   v
COMMIT              ROLLBACK
|                   |
+---------+---------+
|
v
CLOSE
|
v
Connection returned to pool
```

The critical production invariant is:
*Every request-scoped Session must eventually release its database resources.*

## 15. Evidence From app/db/session.py
Required repository evidence

The final research should include the actual implementation from our codebase. Note that while `app/db/session.py` handles session creation and closure via an `async with` block, explicit `commit` and `rollback` operations are delegated to the service layer (e.g., `app/services/task_service.py`) for finer transaction control.

Specifically document:
- **Session creation:** `app/db/session.py:18`
- **Commit:** `app/services/task_service.py:231`
- **Rollback:** `app/services/task_service.py:235`
- **Close:** `app/db/session.py:18` (implicitly via `async with` exiting context after line 19)

**Evidence template**
```
Request enters endpoint
|
v
get_db()
|
Session created
app/db/session.py:18
v
endpoint receives Session
|
+---- database operations
|
+---- commit: app/services/task_service.py:231
|
+---- rollback: app/services/task_service.py:235
|
v
close: app/db/session.py:19 (implicit via async with)
|
v
connection returned to pool
```

## 16. What Happens If the Session Isn't Closed?
Consider:
```python
def get_db():
    db = SessionLocal()
    yield db
    # no close()
```

This is dangerous because the Session may retain transactional/connection resources.
The connection pool has a finite number of connections.

For example:
```
Pool: [Connection 1] [Connection 2] [Connection 3] [Connection 4] [Connection 5]
```

If requests acquire connections and fail to release them:
```
Request A -> Connection 1
Request B -> Connection 2
Request C -> Connection 3
Request D -> Connection 4
Request E -> Connection 5
Request F -> waiting
Request G -> waiting
```

Eventually the application can experience:
- QueuePool timeout
- Connection acquisition failures
- Increased request latency
- Failed API requests
- Database connection exhaustion

The precise behavior depends on pool configuration and how long connections remain checked out.
SQLAlchemy's `QueuePool` places limits on simultaneous connections, and `pool_timeout` controls how long a checkout waits before failing.

## 17. Connection Pooling
SQLAlchemy normally uses a connection pool so that the application does not create a brand-new database connection for every query.

Conceptually:
```
Application
|
v
Session
|
v
Engine
|
v
+-------------------+
| Connection Pool   |
|                   |
| Conn 1            |
| Conn 2            |
| Conn 3            |
| Conn 4            |
| Conn 5            |
+-------------------+
|
v
Database
```

A connection is checked out when needed and returned to the pool when the associated connection/session resource is released.

## 18. Important Pool Settings
Common settings include:
```python
engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=5,
    pool_timeout=30,
    pool_pre_ping=True,
    pool_recycle=3600,
)
```

These values are examples only. They should not be copied into production without considering database capacity and application concurrency.

**pool_size**
Number of persistent connections maintained by the pool.
For QueuePool, SQLAlchemy documents a default of 5.

**max_overflow**
Additional connections allowed above `pool_size`.
If:
```python
pool_size = 10
max_overflow = 5
```
the maximum simultaneous connections allowed by the pool is:
`10 + 5 = 15`
SQLAlchemy documents this relationship explicitly.

**pool_timeout**
How long a request waits for a connection before the pool gives up.
For example:
`pool_timeout=30`
means a connection checkout can wait up to approximately 30 seconds.

**pool_pre_ping**
Checks whether a connection is still alive when it is checked out.
Example:
`pool_pre_ping=True`
SQLAlchemy normally performs a lightweight database ping and can recycle stale/disconnected connections.
This can be particularly useful when the database, network, proxy, or infrastructure can terminate idle connections.

**pool_recycle**
Controls when pooled connections are recycled.
This can be useful with databases or infrastructure that impose idle connection limits.

## 19. Pool Sizing Is Not "Bigger Is Better"
Increasing:
- `pool_size`
- `max_overflow`
without considering the database can make the problem worse.

For example:
`4 application instances * pool_size 20 = potentially 80 persistent connections`

and with:
`max_overflow = 10`
the theoretical concurrent connection demand can be significantly higher.

Pool sizing should therefore consider:
- Number of application instances
- Worker processes
- Expected concurrency
- Database `max_connections`
- Other applications using the same database
- Query duration
- Connection lifetime
- Traffic patterns

The pool is an application-level resource manager; it does not increase the database's actual capacity.

## 20. Sync vs Async Session Lifecycle
The concepts remain largely the same.

**Sync**
```python
with SessionLocal() as session:
    try:
        ...
        session.commit()
    except:
        session.rollback()
        raise
```

**Async**
```python
async with AsyncSessionLocal() as session:
    try:
        ...
        await session.commit()
    except:
        await session.rollback()
        raise
```

The main difference is that the asynchronous API exposes awaitable database operations.
SQLAlchemy provides `async_sessionmaker` specifically as a factory for creating configured `AsyncSession` instances. It also supports a context manager that begins a transaction and commits/closes it automatically.

## 21. Async Transaction Context
A clean async pattern is:
```python
async with AsyncSessionLocal.begin() as session:
    session.add(user)
```

Conceptually:
```
create AsyncSession
|
v
begin transaction
|
v
database operations
|
+---- success --> COMMIT
|
+---- exception -> ROLLBACK
|
v
close session
```

SQLAlchemy documents `async_sessionmaker.begin()` as a context manager that provides an `AsyncSession`, commits the transaction, and closes the session when the context exits.

## 22. Risks of Async SQLAlchemy
Async SQLAlchemy is not simply "sync SQLAlchemy but faster."
Potential risks include:

1. **Implicit I/O**
   Lazy relationship loading or expired attributes can accidentally require database I/O.
2. **Session sharing**
   A single `AsyncSession` must not be shared between concurrent tasks.
3. **Async driver requirements**
   The database driver must support the async SQLAlchemy architecture.
4. **More complex debugging**
   The execution flow includes:
   `async -> await -> event loop -> concurrent tasks`
5. **Mixed sync/async code**
   Calling blocking synchronous database or network operations inside an async endpoint can still block the event loop.

Therefore:
`async endpoint + sync blocking DB operation`
does not automatically provide non-blocking behavior.

## 23. Optional Endpoint-Level Comparison
A minimal comparison could use the same operation.

**Sync**
```python
@app.get("/users/{user_id}")
def get_user(
    user_id: int,
    session: Session = Depends(get_db),
):
    return session.get(User, user_id)
```

**Async**
```python
@app.get("/users/{user_id}")
async def get_user(
    user_id: int,
    session: AsyncSession = Depends(get_async_db),
):
    result = await session.execute(
        select(User).where(User.id == user_id)
    )
    return result.scalar_one_or_none()
```

The application logic is conceptually identical:
`receive ID | query database | return user`
The primary difference is the I/O execution model and API surface.


## 25. Engineering Conclusion
The important distinction is:
`Sync vs Async | +---- execution/concurrency model`
while:
`Session lifecycle | +---- resource and transaction hygiene`

These are related but separate decisions.
A synchronous SQLAlchemy application can still have excellent connection hygiene.
An asynchronous SQLAlchemy application can still leak sessions/connections.

The fundamental production requirement is:
```
Create session
|
v
Use session for a bounded unit of work
|
+---- success --> commit
|
+---- failure --> rollback
|
v
Always close/release resources
```

The SQLAlchemy documentation recommends clear transaction boundaries and short transaction lifetimes.
Therefore, before considering an application-wide async migration, the first priority should be proving that the existing request-scoped Session lifecycle is correct.
