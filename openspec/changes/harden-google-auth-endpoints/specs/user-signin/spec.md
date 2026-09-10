## ADDED Requirements

### Requirement: Sign in with a verified Google access token
The system SHALL accept a Google access token and, when Google confirms it belongs to a
registered, verified-email account matching exactly one account here, issue the same
authentication token password-based signin would issue for that account.

#### Scenario: Valid Google token for a matching account
- **WHEN** a Google access token is submitted whose verified email matches exactly one
  registered account
- **THEN** the request succeeds and returns an authentication token for that account

#### Scenario: Repeated Google signin returns a usable token each time
- **WHEN** the same Google access token's account signs in a second time
- **THEN** the request succeeds again and returns an authentication token

### Requirement: Accept only a token issued for this application
The system SHALL reject a Google access token whose audience does not name a configured client
id of this application, comparing the full configured value rather than a value with incidental
whitespace removed.

#### Scenario: Token issued for a different application
- **WHEN** a Google access token's audience names an application other than this one
- **THEN** the request is rejected and no token is issued

#### Scenario: A later configured client id in a multi-client deployment
- **WHEN** more than one client id is configured and a token's audience matches one that is not
  the first configured
- **THEN** the request succeeds

### Requirement: Require a verified email address
The system SHALL reject a Google access token whose email address Google has not verified.

#### Scenario: Unverified email
- **WHEN** a Google access token's `email_verified` claim is not true
- **THEN** the request is rejected and no token is issued

### Requirement: Refuse an ambiguous or absent matching account
The system SHALL reject a Google signin when no registered account's email matches the token's
verified email, or when more than one does.

#### Scenario: No matching account
- **WHEN** a Google access token's verified email matches no registered account
- **THEN** the request is rejected and no token is issued

#### Scenario: More than one matching account
- **WHEN** a Google access token's verified email matches more than one registered account
- **THEN** the request is rejected and no token is issued

### Requirement: Refuse an embargoed account
The system SHALL reject a Google signin for an account that is embargoed, identically to how it
rejects one with no matching account.

#### Scenario: Embargoed matching account
- **WHEN** a Google access token's verified email matches exactly one registered account and
  that account is embargoed
- **THEN** the request is rejected and no token is issued

### Requirement: Restrict signin to a configured hosted domain
When a hosted-domain restriction is configured, the system SHALL reject a Google access token
whose hosted-domain claim does not match the configured domain, comparing the two
case-insensitively, and SHALL reject a token that carries no hosted-domain claim at all rather
than substituting any other value in its place.

#### Scenario: Matching hosted domain
- **WHEN** a hosted-domain restriction is configured and a token's hosted-domain claim matches it
- **THEN** the request proceeds to the remaining checks

#### Scenario: Hosted domain differs in case only
- **WHEN** a hosted-domain restriction is configured and a token's hosted-domain claim matches it
  under a different letter case
- **THEN** the request proceeds to the remaining checks

#### Scenario: Non-matching hosted domain
- **WHEN** a hosted-domain restriction is configured and a token's hosted-domain claim does not
  match it
- **THEN** the request is rejected and no token is issued

#### Scenario: Hosted-domain claim absent
- **WHEN** a hosted-domain restriction is configured and a token carries no hosted-domain claim
- **THEN** the request is rejected and no token is issued

#### Scenario: No restriction configured
- **WHEN** no hosted-domain restriction is configured
- **THEN** a token with no hosted-domain claim proceeds to the remaining checks

### Requirement: Identical rejection response for every Google-side refusal
The system SHALL respond identically, without distinguishing among them, when a Google access
token is unrecognised by Google, is issued for a different application, is unverified, or fails
the hosted-domain restriction.

#### Scenario: Any Google-side refusal
- **WHEN** a Google signin is rejected for any reason Google's own check or the audience or
  hosted-domain checks cover
- **THEN** the response does not reveal which of those checks failed

### Requirement: Never return a token in a rejection
The system SHALL NOT include an authentication token in the response to a rejected Google signin.

#### Scenario: Rejected signin response
- **WHEN** a Google signin is rejected for any reason
- **THEN** the response body contains no authentication token
