## Purpose

Defines how the MCP server establishes a caller's identity once at login and reuses the
project's own API token as that caller's credential for the rest of the session, so that Google
stands at the front door only and never in the path of an individual tool call.

## ADDED Requirements

### Requirement: Establish a session credential at login
The system SHALL exchange a caller's verified Google access token for this project's own API
token when the caller's MCP session is first established, and SHALL retain that API token as the
caller's session credential.

#### Scenario: First tool call after signing in with Google
- **WHEN** a caller who has just signed in with Google makes their first tool call
- **THEN** exactly one exchange of the Google access token for an API token takes place

#### Scenario: Session credential retained
- **WHEN** the exchange succeeds
- **THEN** the resulting API token is retained as the credential for that caller's session

### Requirement: Refuse a caller this project will not sign in
The system SHALL refuse access to every tool for a caller whose Google access token Google
recognises but for whom the project declines to issue an API token - because no account here
matches them, or because the matching account is embargoed.

#### Scenario: No matching account
- **WHEN** a caller signs in with Google but the project has no account for that address
- **THEN** the caller is refused and no tool executes

#### Scenario: Embargoed account
- **WHEN** a caller's matching account is embargoed
- **THEN** the caller is refused and no tool executes

### Requirement: Refuse a caller Google does not recognise
The system SHALL refuse access to every tool for a caller whose Google access token Google does
not accept.

#### Scenario: Google rejects the access token
- **WHEN** Google does not recognise the caller's access token
- **THEN** the caller is refused and no tool executes

### Requirement: Reuse the session credential for every tool call
The system SHALL use the retained API token as the credential for every tool call in that
session, without exchanging the Google access token again.

#### Scenario: Second and later tool calls
- **WHEN** a caller whose session credential is already established makes a further tool call
- **THEN** the retained API token is used and no further exchange takes place

#### Scenario: Consecutive calls to different tools
- **WHEN** a caller invokes two different tools in the same session
- **THEN** both calls use the same retained API token

### Requirement: Keep Google out of the request path after login
The system SHALL make no network request to Google while serving a tool call for a caller whose
session credential is already established.

#### Scenario: Tool call with an established session
- **WHEN** a tool call is served for a caller whose session credential is already established
- **THEN** no request is made to Google

### Requirement: Recover once from a rejected session credential
When the project's API refuses the retained API token, the system SHALL discard it, exchange the
caller's stored Google access token for a new API token once, and retry the tool call with the
new token.

#### Scenario: Retained token no longer accepted
- **WHEN** a tool call is refused because the retained API token is no longer accepted, and a
  fresh exchange succeeds
- **THEN** the tool call is retried with the new API token and returns its result

#### Scenario: Recovery attempted at most once
- **WHEN** a single tool call triggers the recovery path
- **THEN** at most one fresh exchange is attempted for that call

### Requirement: Fail a call whose recovery does not succeed
The system SHALL fail a tool call, reporting the refusal to the caller, when the retained API
token is refused and the fresh exchange also fails.

#### Scenario: Both the retained token and the fresh exchange are refused
- **WHEN** the retained API token is refused and exchanging the Google access token again also
  fails
- **THEN** the tool call fails and the caller is told they must sign in again

### Requirement: Confine a session credential to its own caller
The system SHALL confine each caller's API token to that caller's session, and SHALL never use
one caller's API token to serve another caller's tool call.

#### Scenario: Two callers with established sessions
- **WHEN** two different callers each have an established session and each makes a tool call
- **THEN** each call is made with that caller's own API token

### Requirement: Keep the session credential out of tool results
The system SHALL never include an API token, a Google access token, or any other credential in
the result of a tool call.

#### Scenario: Any successful tool result
- **WHEN** any tool returns a result
- **THEN** the result contains no API token and no Google access token

#### Scenario: A failing tool result
- **WHEN** a tool call fails, including on the recovery path
- **THEN** the reported failure contains no API token and no Google access token
