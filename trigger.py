import anthropic
import argparse
from datetime import date

# ── Store these as GitHub repository variables (Settings → Secrets and variables → Actions → Variables tab) ──
AGENT_ID        = "agent_0121Q7QMxZq5T7mLfgZwtUXD"        # from your Managed Agents dashboard
ENVIRONMENT_ID  = "env_01Sg7Ax7ZbKNBZPFLmM3DNcJ"
VAULT_ID        = "vlt_011CbG4zp3TC7cLFTFbHFmCZ"        # vault holding your Gmail OAuth credential

MEMORY_STORE_ID = "memstore_019kgkUhdtXVX2CAHGcmZE2"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="", help="Optional date override YYYY-MM-DD")
    args = parser.parse_args()

    run_date = args.date if args.date else str(date.today())

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    session = client.beta.sessions.create(
        agent=AGENT_ID,
        environment_id=ENVIRONMENT_ID,
        vault_ids=[VAULT_ID],
        title=f"AI Funding Radar — {run_date}",
        resources=[
            {
                "type": "memory_store",
                "memory_store_id": MEMORY_STORE_ID,
                "access": "read_write",
                "instructions": (
                    "Stores seen funding round keys for deduplication across daily runs. "
                    "At the start of each run, read all keys from this store and skip any "
                    "funding rounds already seen. After compiling the digest, write new "
                    "round keys back in the format: startup_name+round_stage+date."
                ),
            }
        ],
        metadata={
            "run_date": run_date,
            "trigger": "github_actions",
        },
    )

    print(f"✅ Session created: {session.id}")
    print(f"   Status: {session.status}")
    print(f"   Date: {run_date}")
    print(f"   Memory store: {MEMORY_STORE_ID}")

if __name__ == "__main__":
    main()
