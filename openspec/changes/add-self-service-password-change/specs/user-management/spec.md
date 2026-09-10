## ADDED Requirements

### Requirement: Self-service password change
An authenticated user SHALL be able to change their own password by supplying their current
password and a new password. The system SHALL verify the current password before setting the
new one, and SHALL reject the request, leaving the password unchanged, if the current password
is wrong.

#### Scenario: Successful self-service change
- **WHEN** an authenticated user submits their correct current password and a new password that
  meets the strength requirement
- **THEN** the system sets the new password and the response confirms success without echoing
  either password

#### Scenario: Wrong current password
- **WHEN** an authenticated user submits an incorrect current password
- **THEN** the system rejects the request, the password is unchanged, and the response does not
  reveal the correct password

#### Scenario: Weak new password
- **WHEN** an authenticated user submits a correct current password but a new password that does
  not meet the strength requirement
- **THEN** the system rejects the request and the password is unchanged

#### Scenario: Unauthenticated request
- **WHEN** a request to change a password arrives with no valid authentication credential
- **THEN** the system rejects the request before checking any password, and no password is
  changed

#### Scenario: A password is never echoed back
- **WHEN** a self-service password-change request succeeds or fails for any reason
- **THEN** the response body never contains the current password or the new password
