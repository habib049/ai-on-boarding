# Traceability: add-self-service-password-change

| Requirement / Scenario (`specs/user-management/spec.md`) | Code | Test |
|---|---|---|
| Self-service password change - Successful self-service change | `sdd_django_demo/api/views.py::SelfChangePasswordView.post` (verify, set password, delete tokens) | `sdd_django_demo/api/test_self_change_password.py::test_a_correct_current_password_and_valid_new_password_succeed` |
| Self-service password change - Wrong current password | `SelfChangePasswordView.post` (`check_password` guard) | `test_a_wrong_current_password_is_rejected_and_nothing_changes` |
| Self-service password change - Weak new password | `sdd_django_demo/api/serializers.py::SelfChangePasswordSerializer.new_password` (`validate_password_strength`) | `test_a_weak_new_password_is_rejected_and_nothing_changes` |
| Self-service password change - Unauthenticated request | `SelfChangePasswordView.permission_classes = [IsAuthenticated]` | `test_an_unauthenticated_caller_cannot_change_a_password` |
| Self-service password change - A password is never echoed back | `SelfChangePasswordView.post` response body (`{'detail': ...}` only) | `test_a_successful_change_response_never_contains_either_password`, `test_a_rejected_changes_response_never_contains_either_password` |
| (supporting, not a distinct scenario) token invalidation on success | `SelfChangePasswordView.post` (`Token.objects.filter(user=request.user).delete()`) | `test_a_successful_change_invalidates_the_callers_own_token` |
