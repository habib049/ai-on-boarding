# Traceability: harden-google-auth-endpoints

Every requirement in `specs/user-signin/spec.md`'s ADDED section and `specs/user-management/spec.md`,
the code that implements it, and the test that protects it.

## user-signin (ADDED: Google signin)

| Requirement | Code | Test |
|---|---|---|
| Sign in with a verified Google access token | `mcp_views.GoogleAuthView.post`; `google_auth.resolve_google_user` | `test_a_matching_account_signs_in`, `test_signing_in_a_second_time_succeeds_again` |
| Accept only a token issued for this application | `google_auth.verify_access_token`'s audience check; `settings.GOOGLE_OAUTH_CLIENT_IDS` (stripped) | `test_a_token_for_a_different_application_is_rejected`, `test_a_later_configured_client_id_in_a_multi_client_deployment_is_accepted` |
| Require a verified email address | `google_auth.verify_access_token`'s `email_verified` check | `test_an_unverified_email_is_rejected` |
| Refuse an ambiguous or absent matching account | `google_auth.resolve_google_user` | `test_no_matching_account_is_rejected`, `test_more_than_one_matching_account_is_rejected` |
| Refuse an embargoed account | `mcp_views.GoogleAuthView.post` (`is_user_embargoed`) | `test_an_embargoed_account_is_rejected` |
| Restrict signin to a configured hosted domain | `google_auth._matches_hosted_domain` | `test_a_matching_hosted_domain_is_accepted`, `test_a_hosted_domain_differing_only_in_case_is_accepted`, `test_a_non_matching_hosted_domain_is_rejected`, `test_an_absent_hosted_domain_claim_is_rejected_when_a_restriction_is_configured`, `test_no_hosted_domain_claim_is_fine_when_no_restriction_is_configured` |
| Identical rejection response for every Google-side refusal | `mcp_views.GOOGLE_REJECTION_BODY` (pre-existing, now tested) | `test_every_google_side_refusal_gives_the_same_response` |
| Never return a token in a rejection | `mcp_views.GoogleAuthView.post` | `test_no_rejection_response_carries_a_token` (parametrized over both rejection paths) |

## user-management (new capability)

| Requirement | Code | Test |
|---|---|---|
| List signed-up users | `mcp_views.UserListView` | `test_an_authenticated_caller_can_list_users` |
| Filter the user list by country | `mcp_views.UserListView.get_queryset` (`iexact`) | `test_filtering_by_country_returns_only_matching_users`, `test_country_filter_is_case_insensitive` |
| Require admin privileges to list users | `mcp_views.UserListView.permission_classes = [IsAdminUser]` | `test_listing_without_authentication_is_rejected`, `test_listing_by_an_authenticated_non_admin_is_rejected` |
| Never expose an email address or internal id in the user list | `serializers.UserAccountSerializer.Meta.fields` (`id` and `email` removed) | `test_unfiltered_listing_contains_no_email_address`, `test_filtered_listing_contains_no_email_address`, `test_unfiltered_listing_contains_no_internal_id`, `test_filtered_listing_contains_no_internal_id` |
| Let an admin reset a user's password | `mcp_views.AdminChangePasswordView` | `test_an_admin_resets_a_valid_password` |
| Refuse a non-admin resetting a password | `mcp_views.AdminChangePasswordView.permission_classes = [IsAdminUser]` | `test_a_non_admin_cannot_reset_a_password`, `test_an_unauthenticated_caller_cannot_reset_a_password` |
| Reject a password reset for a nonexistent user | `mcp_views.AdminChangePasswordView.post` (`get_object_or_404`) | `test_resetting_a_nonexistent_users_password_is_rejected` |
| Reject a weak new password | `serializers.validate_password_strength` | `test_a_weak_new_password_is_rejected` |
| Never return the new password | `mcp_views.AdminChangePasswordView.post` (`Response({'detail': ...})`) | `test_a_successful_reset_response_never_contains_the_new_password`, `test_a_rejected_resets_response_never_contains_the_submitted_password` |

## Other fixes (not spec-carrying, but part of this change)

| Fix | Code | Test |
|---|---|---|
| `GOOGLE_OAUTH_CLIENT_IDS` whitespace fix | `settings.py` | Covered indirectly by `test_a_later_configured_client_id_in_a_multi_client_deployment_is_accepted`, which fails without the fix (a comma-separated second id would carry a leading space) |

## Falsifiability

`_matches_hosted_domain` was changed to fall back to the email's domain when `hd` is absent
(the exact bug this change fixes). `test_an_absent_hosted_domain_claim_is_rejected_when_a_restriction_is_configured`
failed, and only that test; the other 15 in `test_google_auth.py` stayed green. The change was
reverted and all 16 pass again.

## Suite results

`sdd_django_demo/`: 172 passed.
