"""
Email sending via Resend.
Falls back to console logging in development.
"""
import resend
from ..config import settings


def _send(to: str, subject: str, html: str):
    if not settings.resend_api_key:
        # Dev mode: print to console
        print(f"\n📧 EMAIL (dev mode)\n  To: {to}\n  Subject: {subject}\n  ---\n  {html}\n")
        return

    resend.api_key = settings.resend_api_key
    resend.Emails.send({
        "from": f"{settings.email_from_name} <{settings.email_from}>",
        "to": [to],
        "subject": subject,
        "html": html,
    })


def send_magic_link(email: str, token: str, purpose: str = "login"):
    url = f"{settings.frontend_url}/auth/verify?token={token}&purpose={purpose}"
    if purpose == "login":
        subject = "Your login link — Agent Marketplace"
        body = f"""
        <p>Click below to log in to Agent Marketplace. This link expires in 15 minutes.</p>
        <p><a href="{url}" style="background:#000;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">Log in →</a></p>
        <p style="color:#666;font-size:12px;">If you didn't request this, ignore this email.</p>
        """
    elif purpose == "claim":
        subject = "Claim your agent — Agent Marketplace"
        body = f"""
        <p>Your agent is waiting to be claimed! Click below to link it to your account.</p>
        <p><a href="{url}" style="background:#000;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">Claim Agent →</a></p>
        <p style="color:#666;font-size:12px;">This link expires in 15 minutes.</p>
        """
    else:
        subject = "Verify your email — Agent Marketplace"
        body = f"""
        <p>Verify your email address to get started.</p>
        <p><a href="{url}" style="background:#000;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">Verify Email →</a></p>
        """
    _send(email, subject, body)


def send_task_assigned(reviewer_email: str, task_id: str, description: str, commission: float):
    url = f"{settings.frontend_url}/tasks/{task_id}"
    _send(
        reviewer_email,
        "New review task available — Agent Marketplace",
        f"""
        <p>A new review task has been assigned to your queue.</p>
        <p><strong>Task:</strong> {description}</p>
        <p><strong>Commission:</strong> ${commission:.2f}</p>
        <p><a href="{url}" style="background:#000;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">Review Task →</a></p>
        """
    )


def send_task_completed(owner_email: str, task_id: str, decision: str, feedback: str):
    url = f"{settings.frontend_url}/workflows"
    _send(
        owner_email,
        f"Review decision: {decision.upper()} — Agent Marketplace",
        f"""
        <p>A reviewer has submitted their decision on your task.</p>
        <p><strong>Decision:</strong> {decision.upper()}</p>
        <p><strong>Feedback:</strong> {feedback or 'No feedback provided'}</p>
        <p><a href="{url}" style="background:#000;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">View Workflows →</a></p>
        """
    )
