"""The sign-in email: an HTML page, built from tables with inline styles as
email clients need, and the same in plain text for those that show no HTML."""

from dataclasses import dataclass
from html import escape

NAVY = "#16233f"
GOLD = "#a87f35"
MUTED = "#6b7280"


@dataclass(frozen=True)
class SignInEmail:
    subject: str
    text: str
    html: str


def sign_in_email(code: str, link: str, minutes: int, welcome: bool) -> SignInEmail:
    subject = "Welcome to Portcullis" if welcome else "Sign in to Portcullis"
    lead = (
        "Welcome! Your account is one click away."
        if welcome
        else "Here's your way back in."
    )
    text = (
        f"{subject}\n\n{lead}\n\n"
        f"Sign in with this link:\n{link}\n\n"
        f"Or enter this code: {code}\n\n"
        f"Both work once, for {minutes} minutes.\n"
        "If you didn't ask to sign in, ignore this email: no one gets in "
        "without it."
    )
    digits = "".join(
        f'<span style="display:inline-block;width:40px;margin:0 3px;'
        f"padding:10px 0;border:1px solid #e5e7eb;border-radius:8px;"
        f'background:#ffffff">{digit}</span>'
        for digit in code
    )
    html = f"""<!doctype html>
<html>
<body style="margin:0;padding:0;background:#f4f4f5">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
  style="background:#f4f4f5;padding:40px 16px;font-family:-apple-system,
  BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
  style="max-width:480px;background:#ffffff;border-radius:16px;
  overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08)">
  <tr><td style="background:{NAVY};padding:28px 32px">
    <span style="font-family:Georgia,'Times New Roman',serif;font-size:22px;
      font-weight:bold;color:#ffffff;letter-spacing:0.5px">Portcullis</span>
    <span style="display:block;margin-top:4px;font-size:12px;color:{GOLD};
      letter-spacing:2px;text-transform:uppercase">The control layer for AI
      agents</span>
  </td></tr>
  <tr><td style="padding:36px 32px 8px">
    <h1 style="margin:0 0 8px;font-family:Georgia,'Times New Roman',serif;
      font-size:26px;color:{NAVY}">{escape(subject)}</h1>
    <p style="margin:0 0 28px;font-size:15px;line-height:22px;color:{MUTED}">
      {escape(lead)}</p>
    <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
      <tr><td align="center" style="border-radius:10px;background:{NAVY}">
        <a href="{escape(link)}" style="display:block;padding:14px 24px;
          font-size:16px;font-weight:600;color:#ffffff;text-decoration:none">
          Sign in to Portcullis &rarr;</a>
      </td></tr>
    </table>
    <p style="margin:32px 0 12px;font-size:13px;color:{MUTED};text-align:center">
      Or enter this code on the sign-in screen</p>
    <div style="text-align:center;font-family:'SF Mono',Menlo,Consolas,monospace;
      font-size:24px;font-weight:600;color:{NAVY}">{digits}</div>
  </td></tr>
  <tr><td style="padding:28px 32px 32px">
    <p style="margin:0;padding-top:20px;border-top:1px solid #f0f0f1;
      font-size:12px;line-height:18px;color:{MUTED}">
      The link and the code work once, for {minutes} minutes.<br>
      If you didn't ask to sign in, ignore this email: no one gets in without
      it.</p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
    return SignInEmail(subject=subject, text=text, html=html)
