from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from accounts import auth_views, views

urlpatterns = [
    path("config/", auth_views.AuthConfigView.as_view(), name="auth-config"),
    path("google/", auth_views.GoogleAuthView.as_view(), name="auth-google"),
    path("signup/", auth_views.SignupStartView.as_view(), name="auth-signup"),
    path("signup/verify/", auth_views.SignupVerifyView.as_view(), name="auth-signup-verify"),
    path("signup/resend/", auth_views.SignupResendView.as_view(), name="auth-signup-resend"),
    path("password/forgot/", auth_views.PasswordForgotView.as_view(), name="auth-password-forgot"),
    path("password/reset/", auth_views.PasswordResetView.as_view(), name="auth-password-reset"),
    path("password/resend/", auth_views.PasswordResetResendView.as_view(), name="auth-password-resend"),
    path("login/", auth_views.LoginView.as_view(), name="auth-login"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("me/", views.MeView.as_view(), name="auth-me"),
]
