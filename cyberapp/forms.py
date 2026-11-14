"""WTForms definitions. Every form is CSRF-protected by Flask-WTF."""
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, EqualTo, Length, Optional, Regexp, ValidationError

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"


def strong_password(form, field):
    value = field.data or ""
    if not (any(c.isalpha() for c in value) and any(c.isdigit() for c in value)):
        raise ValidationError("Use at least one letter and one number.")


class RegisterForm(FlaskForm):
    username = StringField("Username", validators=[
        DataRequired(), Length(3, 40),
        Regexp(r"^[A-Za-z0-9_.-]+$", message="Use letters, numbers, dots, dashes or underscores."),
    ])
    email = StringField("Email", validators=[DataRequired(), Length(max=120),
                                             Regexp(EMAIL_PATTERN, message="Enter a valid email address.")])
    password = PasswordField("Password", validators=[DataRequired(), Length(8, 128), strong_password])
    confirm = PasswordField("Confirm password", validators=[
        DataRequired(), EqualTo("password", message="Passwords must match."),
    ])


class LoginForm(FlaskForm):
    username = StringField("Username or email", validators=[DataRequired(), Length(max=120)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128)])
    remember = BooleanField("Keep me signed in")


class ChangePasswordForm(FlaskForm):
    current = PasswordField("Current password", validators=[DataRequired(), Length(max=128)])
    password = PasswordField("New password", validators=[DataRequired(), Length(8, 128), strong_password])
    confirm = PasswordField("Confirm new password", validators=[
        DataRequired(), EqualTo("password", message="Passwords must match."),
    ])


class UserAdminForm(FlaskForm):
    role = SelectField("Role", choices=[])  # choices are set in the view from Role.ALL
    active = BooleanField("Account active")


class CaseForm(FlaskForm):
    url = StringField("Suspicious URL", validators=[DataRequired(), Length(max=2048)])
    channel = SelectField("Where did you receive it?", choices=[])  # set from CHANNELS in the view
    description = TextAreaField("Description (optional)", validators=[Optional(), Length(max=2000)])
