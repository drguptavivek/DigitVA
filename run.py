import sqlalchemy as sa
from app import create_app, db

app = create_app()


@app.shell_context_processor
def make_shell_context():
    return {
        "sa": sa,
        "db": db,
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
