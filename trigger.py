import anthropic
import argparse
import httpx
import os
import time
from datetime import date

AGENT_ID        = "agent_0121Q7QMxZq5T7mLfgZwtUXD"
ENVIRONMENT_ID  = "env_01Sg7Ax7ZbKNBZPFLmM3DNcJ"
VAULT_ID        = "vlt_011CbG4zp3TC7cLFTFbHFmCZ"
MEMORY_STORE_ID = "memstore_013vh5eFdSoGH636PpSjHJKy"
RECIPIENT       = "mohan.anand.mnnit@gmail.com"

def get_or_create_memory_store(client):
    if MEMORY_STORE_ID:
        return MEMORY_STORE_ID
    print("⚙️  No memory store ID set — creating one...")
    store = client.beta.memory_stores.create(
        name="AI Funding Radar",
        description="Stores seen funding round keys for deduplication across daily runs.",
    )
    print(f"✅ Memory store created: {store.id}")
    return store.id

def wait_for_completion(client, session_id, timeout=1800):
    """
    Wait until the session is truly done:
    - Must have been 'running' at least once (agent started work)
    - Then goes 'idle' with a stop_reason that is NOT 'requires_action'
    """
    print("⏳ Waiting for agent to finish...")
    start = time.time()
    has_been_running = False

    while time.time() - start < timeout:
        s = client.beta.sessions.retrieve(session_id)
        print(f"   Status: {s.status}")

        if s.status == "running":
            has_been_running = True

        elif s.status == "idle" and has_been_running:
            # Fetch the latest idle event to check stop_reason
            events = client.beta.sessions.events.list(session_id=session_id)
            for event in reversed(events.data):
                if event.type == "session.status_idle":
                    stop_reason = getattr(event, "stop_reason", None)
                    reason_type = (stop_reason or {}).get("type") if isinstance(stop_reason, dict) else getattr(stop_reason, "type", None)
                    if reason_type != "requires_action":
                        print("✅ Agent completed successfully.")
                        return True
                    else:
                        print("   Agent idle but awaiting action — continuing to wait...")
                    break

        elif s.status == "terminated":
            raise RuntimeError("Session terminated unexpectedly")

        time.sleep(15)

    raise TimeoutError("Agent did not complete within 30 minutes")

def get_digest(client, session_id):
    """
    Extract the longest agent.message text — the digest.
    Falls back gracefully if the agent sent the email directly and only
    produced a short confirmation message.
    """
    events = client.beta.sessions.events.list(session_id=session_id)
    best = ""
    for event in events.data:
        if event.type == "agent.message":
            for block in event.content:
                if block.type == "text" and len(block.text) > len(best):
                    best = block.text
    if not best:
        raise ValueError("No agent.message found in session events")
    return best

def send_email(digest_html, run_date):
    """Send digest via Resend."""
    api_key = os.environ["RESEND_API_KEY"]
    response = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": "AI Funding Radar <onboarding@resend.dev>",
            "to": [RECIPIENT],
            "subject": f"🚀 AI Funding Radar — {run_date}",
            "html": digest_html.replace("\n", "<br>"),
        },
        timeout=30,
    )
    response.raise_for_status()
    print(f"✅ Email sent via Resend! ID: {response.json().get('id')}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="", help="Optional date override YYYY-MM-DD")
    args = parser.parse_args()
    run_date = args.date if args.date else str(date.today())

    client = anthropic.Anthropic()
    memory_store_id = get_or_create_memory_store(client)

    session = client.beta.sessions.create(
        agent=AGENT_ID,
        environment_id=ENVIRONMENT_ID,
        vault_ids=[VAULT_ID],
        title=f"AI Funding Radar — {run_date}",
        resources=[{
            "type": "memory_store",
            "memory_store_id": memory_store_id,
            "access": "read_write",
            "instructions": (
                "Stores seen funding round keys for deduplication across daily runs. "
                "At the start of each run, read all keys from this store and skip any "
                "funding rounds already seen. After compiling the digest, write new "
                "round keys back in the format: startup_name+round_stage+date."
            ),
        }],
        metadata={"run_date": run_date, "trigger": "github_actions"},
    )
    print(f"✅ Session created: {session.id}")

    client.beta.sessions.events.send(
        session_id=session.id,
        events=[{"type": "user.message", "content": [{"type": "text", "text": f"run {run_date}"}]}]
    )
    print("✅ Trigger message sent — agent is now running.")

    wait_for_completion(client, session.id)

    digest = get_digest(client, session.id)
    print(f"✅ Digest compiled ({len(digest)} chars)")

    # Only call send_email if the agent didn't already send via Gmail MCP.
    # If agent sends via Gmail, this is your fallback Resend delivery.
    send_email(digest, run_date)

if __name__ == "__main__":
    main()
