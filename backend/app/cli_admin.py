"""flask create-superadmin: first administrator of a fresh install (and password recovery).

    docker compose exec backend flask --app run create-superadmin --email you@example.com

The password is asked twice on the terminal (hidden), or read from the environment variable named by
--password-env for non-interactive setups. There is no default password. The account gets the
Enterprise plan, as the old start.sh did, so the first admin is not limited by the Free quota.
"""
import os

import click
from flask.cli import with_appcontext

MIN_PASSWORD_LENGTH = 8  # same rule as PUT /api/auth/me


def _read_password(password_env: str | None) -> str:
    if password_env:
        password = os.environ.get(password_env, "")
        if not password:
            raise click.ClickException(f"Environment variable {password_env} is empty or not set.")
    else:
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise click.ClickException(f"The password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    return password


@click.command("create-superadmin")
@click.option("--email", required=True, help="Login email of the superadmin.")
@click.option("--name", "full_name", default="", help="Display name (optional).")
@click.option("--password-env", default=None, metavar="VAR",
              help="Read the password from this environment variable instead of prompting.")
@click.option("--reset-password", is_flag=True,
              help="The user exists: set a new password and make it an active superadmin.")
@with_appcontext
def create_superadmin_command(email: str, full_name: str, password_env: str | None, reset_password: bool):
    """Create the first superadmin, or reset an existing user's password with --reset-password."""
    from app.models import AuditLog, Plan, Subscription, User, db
    from app.models.plan import PlanTier
    from app.models.user import Role

    email = email.strip().lower()
    if "@" not in email:
        raise click.ClickException("Invalid email address.")
    user = User.query.filter_by(email=email).first()
    if user and not reset_password:
        raise click.ClickException(f"User {email} already exists. Use --reset-password to set a new password.")
    if not user and reset_password:
        raise click.ClickException(f"User {email} does not exist. Run the command without --reset-password.")

    password = _read_password(password_env)
    created = user is None
    if created:
        # Query before session.add: autoflush would insert the user before it has a password
        plan = Plan.query.filter_by(tier=PlanTier.ENTERPRISE).first()
        user = User(email=email, full_name=full_name, is_verified=True)
    elif full_name:
        user.full_name = full_name
    user.role = Role.SUPERADMIN
    user.is_active = True
    user.set_password(password)
    if created:
        db.session.add(user)
        if plan:
            db.session.add(Subscription(user=user, plan=plan))
    db.session.flush()
    AuditLog.log("superadmin_created_cli" if created else "superadmin_password_reset_cli",
                 user_id=user.id, resource_type="user", resource_id=user.id)
    db.session.commit()
    click.echo(f"Superadmin {email} {'created' if created else 'updated'}.")
