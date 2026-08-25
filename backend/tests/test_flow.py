import os
os.environ["DATABASE_URL"]="sqlite:///./test_survey_exchange.db"
os.environ["DEV_MODE"]="true"
from fastapi.testclient import TestClient
from app.main import app, Base, engine

def h(user,email): return {"X-Demo-User":user,"X-Demo-Email":email}
def setup_module(): Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
def profile(user,email,gender):
    return {"roll_number":user,"gender":gender,"program":"B.Tech","batch":2024,"department":"CSE","year":3}
def test_verified_completion_moves_locked_credit_and_fills_quota():
    with TestClient(app) as c:
        creator=h("creator","creator@nitc.ac.in"); respondent=h("student","student@nitc.ac.in")
        c.put("/me",json=profile("B2401","creator@nitc.ac.in","Female"),headers=creator)
        c.put("/me",json=profile("B2402","student@nitc.ac.in","Male"),headers=respondent)
        # Seed earned credits through the explicit local dev database only.
        from app.main import SessionLocal, Profile
        db=SessionLocal(); db.get(Profile,"creator").credits=5; db.commit(); db.close()
        created=c.post("/surveys",json={"title":"Career study","description":"A short research study about career choices.","google_form_url":"https://docs.google.com/forms/d/e/example/viewform","form_id":"form-1","participation_field_entry":"entry.123","estimated_minutes":5,"reward_per_response":5,"requirements":[{"department":"CSE","year":3,"gender":"Male","quota":1}]},headers=creator)
        assert created.status_code==201; result=created.json()
        joined=c.post(f"/surveys/{result['id']}/participate",headers=respondent).json()
        accepted=c.post("/webhooks/google-form",json={"survey_id":result["id"],"participation_token":joined["token"],"form_id":"form-1","webhook_secret":result["webhook_secret"]})
        assert accepted.status_code==200 and accepted.json()["survey_status"]=="COMPLETED"
        assert c.get("/me",headers=respondent).json()["available_credits"]==5
        assert c.post("/webhooks/google-form",json={"survey_id":result["id"],"participation_token":joined["token"],"form_id":"form-1","webhook_secret":result["webhook_secret"]}).json()["idempotent"] is True
