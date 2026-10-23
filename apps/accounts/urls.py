from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import (
    AvatarView,
    CurrentUserView,
    LoginView,
    RegisterView,
    UserDetailView,
)
from apps.interactions.views import (
    UserFollowersView,
    UserFollowingView,
    UserFollowView,
)

urlpatterns = [
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("users/me/", CurrentUserView.as_view(), name="current-user"),
    path("users/me/avatar/", AvatarView.as_view(), name="current-user-avatar"),
    path("users/<str:username>/follow/", UserFollowView.as_view(), name="user-follow"),
    path("users/<str:username>/followers/", UserFollowersView.as_view(), name="user-followers"),
    path("users/<str:username>/following/", UserFollowingView.as_view(), name="user-following"),
    path("users/<str:username>/", UserDetailView.as_view(), name="user-detail"),
]
