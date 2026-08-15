"""Domain services: the single source of truth for tasks & journal logic.

Both the REST API (`app.api.*`) and the assistant's tools (`app.core.tools`) call
these functions, so a record created by tapping a button and one created by the
assistant are identical and validated the same way. Services are synchronous DB
code (the DB is sync); callers wrap them in `run_in_threadpool` on the async path.
"""
