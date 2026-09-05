## Purpose

Lets an authenticated caller list the signed-up users on record, and lets an admin reset a
user's password, without exposing any user's internal id or email address to a caller who only
needs to see who has signed up and from where.

## ADDED Requirements

### Requirement: List signed-up users
The system SHALL let an authenticated caller retrieve the list of registered users, each
represented by username, country, and signup date.

#### Scenario: Listing succeeds for an authenticated caller
- **WHEN** an authenticated caller requests the user list
- **THEN** the request succeeds and returns every registered user's username, country, and
  signup date

### Requirement: Filter the user list by country
The system SHALL let an authenticated caller filter the user list to a single country, matched
case-insensitively.

#### Scenario: Filtering to a country with matching users
- **WHEN** an authenticated caller requests the user list filtered to a country in which some
  registered users are located
- **THEN** the request succeeds and returns only users located in that country

#### Scenario: Country filter differs in case only
- **WHEN** the requested country differs only in letter case from how a user's country is
  recorded
- **THEN** that user is included in the filtered result

### Requirement: Require authentication to list users
The system SHALL reject a request for the user list from a caller who has not authenticated.

#### Scenario: Unauthenticated request
- **WHEN** the user list is requested without authentication
- **THEN** the request is rejected

### Requirement: Never expose an email address in the user list
The system SHALL NOT include any user's email address in the user list response, in filtered or
unfiltered form.

#### Scenario: Unfiltered listing
- **WHEN** an authenticated caller requests the user list
- **THEN** no entry in the response contains an email address

#### Scenario: Filtered listing
- **WHEN** an authenticated caller requests the user list filtered by country
- **THEN** no entry in the response contains an email address

### Requirement: Let an admin reset a user's password
The system SHALL let an authenticated admin set a new password for any user, given that user's
identifier and a new password meeting the system's password strength requirement.

#### Scenario: Admin resets a valid password
- **WHEN** an authenticated admin submits a new password meeting the strength requirement for an
  existing user
- **THEN** the request succeeds and that user's password is changed to the submitted one

### Requirement: Refuse a non-admin resetting a password
The system SHALL reject a password reset submitted by an authenticated caller who is not an
admin, and SHALL reject one submitted without authentication.

#### Scenario: Non-admin caller
- **WHEN** an authenticated caller who is not an admin submits a password reset for any user
- **THEN** the request is rejected and the password is not changed

#### Scenario: Unauthenticated caller
- **WHEN** a password reset is submitted without authentication
- **THEN** the request is rejected and the password is not changed

### Requirement: Reject a password reset for a nonexistent user
The system SHALL reject a password reset naming a user identifier that matches no account.

#### Scenario: Unknown user identifier
- **WHEN** an admin submits a password reset naming a user identifier that matches no account
- **THEN** the request is rejected and no password is changed

### Requirement: Reject a weak new password
The system SHALL reject a password reset whose new password does not meet the system's password
strength requirement.

#### Scenario: Weak new password
- **WHEN** an admin submits a password reset with a new password that does not meet the
  strength requirement
- **THEN** the request is rejected and the password is not changed

### Requirement: Never return the new password
The system SHALL NOT include the new password, in any form, in the response to a password reset
request, successful or not.

#### Scenario: Successful reset
- **WHEN** an admin's password reset succeeds
- **THEN** the response body does not contain the new password in any form

#### Scenario: Rejected reset
- **WHEN** a password reset is rejected for any reason
- **THEN** the response body does not contain the submitted new password in any form
