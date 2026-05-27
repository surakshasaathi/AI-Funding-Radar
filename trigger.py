import anthropic
import argparse
import httpx
import os
import re
import time
from datetime import date

AGENT_ID        = "agent_0121Q7QMxZq5T7mLfgZwtUXD"
ENVIRONMENT_ID  = "env_01Sg7Ax7ZbKNBZPFLmM3DNcJ"
VAULT_ID        = "vlt_011CbG4zp3TC7cLFTFbHFmCZ"
MEMORY_STORE_ID = "memstore_013vh5eFdSoGH636PpSjHJKy"
RECIPIENT       = "claudesender2026@gmail.com"

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
    print("⏳ Waiting for agent to finish...")
    start = time.time()
    has_been_running = False

    while time.time() - start < timeout:
        s = client.beta.sessions.retrieve(session_id)
        print(f"   Status: {s.status}")

        if s.status == "running":
            has_been_running = True

        elif s.status == "idle" and has_been_running:
            events = client.beta.sessions.events.list(session_id=session_id)
            for event in reversed(events.data):
                if event.type == "session.status_idle":
                    stop_reason = getattr(event, "stop_reason", None)
                    reason_type = (
                        stop_reason.get("type")
                        if isinstance(stop_reason, dict)
                        else getattr(stop_reason, "type", None)
                    )
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
    """Extract only the final digest between sentinel delimiters."""
    events = client.beta.sessions.events.list(session_id=session_id)
    
    # Concatenate all agent.message text
    full_text = []
    for event in events.data:
        if event.type == "agent.message":
            for block in event.content:
                if block.type == "text" and block.text.strip():
                    full_text.append(block.text)
    
    combined = "\n".join(full_text)
    
    # Extract only what's between the delimiters
    start_marker = "<<<DIGEST_START>>>"
    end_marker = "<<<DIGEST_END>>>"
    
    start_idx = combined.find(start_marker)
    end_idx = combined.find(end_marker)
    
    if start_idx == -1 or end_idx == -1:
        raise ValueError("Digest delimiters not found in session output")
    
    digest = combined[start_idx + len(start_marker):end_idx].strip()
    
    if not digest:
        raise ValueError("Empty digest extracted between delimiters")
    
    return digest

def digest_to_html(text, run_date):
    """Convert the agent's plain-text digest into styled HTML for Resend."""

    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    lines = text.split("\n")
    html_lines = []

    for line in lines:
        line_esc = esc(line)

        # Separator line → horizontal rule
        if line.startswith("━"):
            html_lines.append("<hr style='border:none;border-top:1px solid #e2e8f0;margin:12px 0;'>")

        # Section headers
        elif "India AI Fundings" in line:
            html_lines.append(f"<h2 style='color:#1a365d;font-size:20px;margin:32px 0 16px;border-bottom:3px solid #3182ce;padding-bottom:8px;'>🇮🇳 {line_esc}</h2>")

        elif "Global AI Fundings" in line:
            html_lines.append(f"<h2 style='color:#1a365d;font-size:20px;margin:32px 0 16px;border-bottom:3px solid #38a169;padding-bottom:8px;'>🌍 {line_esc}</h2>")

        # Startup name line (contains · and is not a field label)
        elif "·" in line and not any(line.startswith(f) for f in ["What They Do", "Founders", "Funding", "Lead", "Other", "Traction", "Summary"]):
            html_lines.append(f"<h3 style='color:#2d3748;font-size:16px;margin:16px 0 8px;'>🏢 {line_esc}</h3>")

        # Field labels — bold label + value
        elif re.match(r"^(What They Do|Founders|Funding|Lead Investor|Other Investors|Traction|Summary):", line):
            parts = line.split(":", 1)
            label = esc(parts[0])
            value = esc(parts[1].strip()) if len(parts) > 1 else ""
            color = "#744210" if parts[0] == "Summary" else "#2d3748"
            bg = "#fffff0" if parts[0] == "Summary" else "transparent"
            padding = "style='background:#fffff0;padding:8px 10px;border-left:3px solid #d69e2e;margin:6px 0;'" if parts[0] == "Summary" else "style='margin:4px 0;'"
            html_lines.append(f"<p {padding}><strong style='color:#4a5568;'>{label}:</strong> <span style='color:{color};'>{value}</span></p>")

        # Footer
        elif "Delivered daily" in line or "Data sourced" in line:
            html_lines.append(f"<p style='color:#718096;font-size:12px;margin:4px 0;'>{line_esc}</p>")

        # Header date line
        elif line.strip() and not line.startswith("AI Funding Radar"):
            html_lines.append(f"<p style='margin:4px 0;color:#4a5568;'>{line_esc}</p>")

        elif line.startswith("AI Funding Radar"):
            html_lines.append(f"<h1 style='color:#1a365d;font-size:28px;margin:0 0 4px;'>🚀 {line_esc}</h1>")

        elif line.strip() == "---" or line.strip() == "":
            html_lines.append("<div style='margin:8px 0;'></div>")

        else:
            html_lines.append(f"<p style='margin:4px 0;'>{line_esc}</p>")

    body = "\n".join(html_lines)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
             max-width:720px;margin:0 auto;padding:24px 16px;background:#f7fafc;color:#2d3748;">
  <div style="background:white;border-radius:12px;padding:32px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
    <div style="background:linear-gradient(135deg,#1a365d,#2b6cb0);color:white;
                border-radius:8px;padding:24px;margin-bottom:24px;text-align:center;">
      <h1 style="margin:0;font-size:26px;color:white;">🚀 AI Funding Radar</h1>
      <p style="margin:8px 0 0;opacity:0.9;font-size:14px;">{run_date} · Your daily briefing on AI startup funding</p>
    </div>
    {body}
    <div style="margin-top:32px;padding-top:16px;border-top:1px solid #e2e8f0;
                text-align:center;color:#a0aec0;font-size:12px;">
      AI Funding Radar · Delivered daily at 7:00 AM IST<br>
      Data sourced from TechCrunch, Inc42, YourStory, Crunchbase, Bloomberg, VCCircle
    </div>
  </div>
</body>
</html>"""

def send_email(html, run_date):
    """Send digest via Resend."""
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise EnvironmentError("RESEND_API_KEY is not set — add it to GitHub Secrets")

    response = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": "AI Funding Radar <onboarding@resend.dev>",
            "to": [RECIPIENT],
            "subject": f"🚀 AI Funding Radar — {run_date}",
            "html": html,
        },
        timeout=30,
    )

    print(f"   Resend status: {response.status_code}")
    if not response.is_success:
        print(f"   Resend error: {response.text}")
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
        events=[{
            "type": "user.message",
            "content": [{"type": "text", "text": f"run {run_date}"}],
        }],
    )
    print("✅ Trigger message sent — agent is now running.")

    wait_for_completion(client, session.id)

    digest = get_digest(client, session.id)
    print(f"✅ Digest compiled ({len(digest)} chars)")
    print(f"   Preview: {digest[:300]}...")

    html = digest_to_html(digest, run_date)
    send_email(html, run_date)
    print(f"🎉 AI Funding Radar run complete for {run_date}")

if __name__ == "__main__":
    main()
