from fastapi import FastAPI

app = FastAPI()

@app.get("/message")
def static_message():
    return {"msg": "Hello from message service!"}



