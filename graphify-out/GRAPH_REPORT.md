# Graph Report - .  (2026-04-21)

## Corpus Check
- 186 files · ~117,454 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1042 nodes · 2366 edges · 85 communities detected
- Extraction: 51% EXTRACTED · 49% INFERRED · 0% AMBIGUOUS · INFERRED: 1171 edges (avg confidence: 0.64)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Adyen Payment Integration|Adyen Payment Integration]]
- [[_COMMUNITY_Agent Runner|Agent Runner]]
- [[_COMMUNITY_Gateway Launcher|Gateway Launcher]]
- [[_COMMUNITY_Data Models|Data Models]]
- [[_COMMUNITY_Utils|Utils]]
- [[_COMMUNITY_Webhooks|Webhooks]]
- [[_COMMUNITY_Android Tests|Android Tests]]
- [[_COMMUNITY_Main Activity|Main Activity]]
- [[_COMMUNITY_Kotlin A2A Client|Kotlin A2A Client]]
- [[_COMMUNITY_Kotlin Message Builder|Kotlin Message Builder]]
- [[_COMMUNITY_Kotlin A2A Types|Kotlin A2A Types]]
- [[_COMMUNITY_HTTP Client|HTTP Client]]
- [[_COMMUNITY_Kotlin Shopping Tools|Kotlin Shopping Tools]]
- [[_COMMUNITY_Kotlin Chat Message|Kotlin Chat Message]]
- [[_COMMUNITY_Kotlin DPC Types|Kotlin DPC Types]]
- [[_COMMUNITY_Kotlin Shopping Types|Kotlin Shopping Types]]
- [[_COMMUNITY_Kotlin Chat UI|Kotlin Chat UI]]
- [[_COMMUNITY_Kotlin ViewModel|Kotlin ViewModel]]
- [[_COMMUNITY_Payment Models|Payment Models]]
- [[_COMMUNITY_Task Management|Task Management]]
- [[_COMMUNITY_Error Handling|Error Handling]]
- [[_COMMUNITY_Message Builder|Message Builder]]
- [[_COMMUNITY_UI Components|UI Components]]
- [[_COMMUNITY_Go Server Main|Go Server Main]]
- [[_COMMUNITY_Notification Service|Notification Service]]
- [[_COMMUNITY_Go Mandates|Go Mandates]]
- [[_COMMUNITY_Go A2A Types|Go A2A Types]]
- [[_COMMUNITY_A2A Protocol Types|A2A Protocol Types]]
- [[_COMMUNITY_Go Agent Executors|Go Agent Executors]]
- [[_COMMUNITY_Go JSON-RPC|Go JSON-RPC]]
- [[_COMMUNITY_Demo Code|Demo Code]]
- [[_COMMUNITY_Python A2A Helpers|Python A2A Helpers]]
- [[_COMMUNITY_Credentials|Credentials]]
- [[_COMMUNITY_Key Management|Key Management]]
- [[_COMMUNITY_Crypto Primitives|Crypto Primitives]]
- [[_COMMUNITY_Auth Tokens|Auth Tokens]]
- [[_COMMUNITY_Catalog & Products|Catalog & Products]]
- [[_COMMUNITY_Session Storage|Session Storage]]
- [[_COMMUNITY_Tool Registry|Tool Registry]]
- [[_COMMUNITY_Request Handlers|Request Handlers]]
- [[_COMMUNITY_Storage & Cache|Storage & Cache]]
- [[_COMMUNITY_Response Formatters|Response Formatters]]
- [[_COMMUNITY_Agent Entry Points|Agent Entry Points]]
- [[_COMMUNITY_Mandate Signing|Mandate Signing]]
- [[_COMMUNITY_A2A Protocol|A2A Protocol]]
- [[_COMMUNITY_Configuration|Configuration]]
- [[_COMMUNITY_Logging|Logging]]
- [[_COMMUNITY_Database|Database]]
- [[_COMMUNITY_Serialization|Serialization]]
- [[_COMMUNITY_Validation|Validation]]
- [[_COMMUNITY_Middleware|Middleware]]
- [[_COMMUNITY_Router|Router]]
- [[_COMMUNITY_Controller|Controller]]
- [[_COMMUNITY_Service Layer|Service Layer]]
- [[_COMMUNITY_Repository|Repository]]
- [[_COMMUNITY_Domain Models|Domain Models]]
- [[_COMMUNITY_Value Objects|Value Objects]]
- [[_COMMUNITY_Events|Events]]
- [[_COMMUNITY_Handlers|Handlers]]
- [[_COMMUNITY_Converters|Converters]]
- [[_COMMUNITY_Formatters|Formatters]]
- [[_COMMUNITY_Parsers|Parsers]]
- [[_COMMUNITY_Factories|Factories]]
- [[_COMMUNITY_Builders|Builders]]
- [[_COMMUNITY_Decorators|Decorators]]
- [[_COMMUNITY_Plugins|Plugins]]
- [[_COMMUNITY_Extensions|Extensions]]
- [[_COMMUNITY_Mixins|Mixins]]
- [[_COMMUNITY_Interfaces|Interfaces]]
- [[_COMMUNITY_Abstract Classes|Abstract Classes]]
- [[_COMMUNITY_Base Classes|Base Classes]]
- [[_COMMUNITY_Helper Functions|Helper Functions]]
- [[_COMMUNITY_Constants|Constants]]
- [[_COMMUNITY_Enums|Enums]]
- [[_COMMUNITY_Flags|Flags]]
- [[_COMMUNITY_Config|Config]]
- [[_COMMUNITY_Options|Options]]
- [[_COMMUNITY_Settings|Settings]]
- [[_COMMUNITY_Parameters|Parameters]]
- [[_COMMUNITY_Arguments|Arguments]]
- [[_COMMUNITY_Inputs|Inputs]]
- [[_COMMUNITY_Outputs|Outputs]]
- [[_COMMUNITY_Results|Results]]
- [[_COMMUNITY_Returns|Returns]]
- [[_COMMUNITY_Responses|Responses]]

## God Nodes (most connected - your core abstractions)
1. `PaymentMandate` - 86 edges
2. `A2aMessageBuilder` - 82 edges
3. `ContactAddress` - 63 edges
4. `CartMandate` - 50 edges
5. `PaymentReceipt` - 48 edges
6. `PaymentRemoteA2aClient` - 42 edges
7. `build()` - 39 edges
8. `PaymentItem` - 38 edges
9. `PaymentResponse` - 37 edges
10. `PaymentCurrencyAmount` - 36 edges

## Surprising Connections (you probably didn't know these)
- `InitiatePayment()` --calls--> `NewA2AClient()`  [INFERRED]
  AP2\samples\go\pkg\roles\merchant_agent\tools.go → AP2\samples\go\pkg\common\http_client.go
- `Gets the user's payment methods from the credentials provider.    These will m` --uses--> `A2aMessageBuilder`  [INFERRED]
  AP2\samples\python\src\roles\shopping_agent\subagents\payment_method_collector\tools.py → AP2\samples\python\src\common\a2a_message_builder.py
- `Gets a payment credential token from the credentials provider.    Args:     u` --uses--> `A2aMessageBuilder`  [INFERRED]
  AP2\samples\python\src\roles\shopping_agent\subagents\payment_method_collector\tools.py → AP2\samples\python\src\common\a2a_message_builder.py
- `Fetches the merchant's on-file payment methods (Mode 2) via A2A.    Use this w` --uses--> `A2aMessageBuilder`  [INFERRED]
  AP2\samples\python\src\roles\shopping_agent\subagents\payment_method_collector\tools.py → AP2\samples\python\src\common\a2a_message_builder.py
- `Exchanges a chosen on-file alias for a PSP charge token via the merchant.    T` --uses--> `A2aMessageBuilder`  [INFERRED]
  AP2\samples\python\src\roles\shopping_agent\subagents\payment_method_collector\tools.py → AP2\samples\python\src\common\a2a_message_builder.py

## Communities

### Community 1 - "Adyen Payment Integration"
Cohesion: 0.0
Nodes (90): _api_base(), _required_env(), _parse_expiry(), _build_zero_auth_body(), _extract_stored_id(), _pick_target_mof_row(), _post_payments(), main() (+82 more)

### Community 6 - "Agent Runner"
Cohesion: 0.0
Nodes (46): main(), Tiny launcher for the three AP2 backend agents.  Usage:     python ops/run_agent, RetryingLlmAgent, LlmAgent, _run_async_impl(), An LLM agent that surfaces errors to the user and then retries., BaseHTTPMiddleware, _Window (+38 more)

### Community 23 - "Gateway Launcher"
Cohesion: 0.0
Nodes (3): _load_dotenv(), Tiny launcher: set the env vars our local-dev gateway expects, then re-enter ``p, Tiny KEY=VALUE loader (no python-dotenv dep). Existing env wins.

### Community 35 - "Data Models"
Cohesion: 0.0
Nodes (0): 

### Community 36 - "Utils"
Cohesion: 0.0
Nodes (0): 

### Community 37 - "Webhooks"
Cohesion: 0.0
Nodes (0): 

### Community 27 - "Android Tests"
Cohesion: 0.0
Nodes (1): ExampleInstrumentedTest

### Community 28 - "Main Activity"
Cohesion: 0.0
Nodes (1): MainActivity

### Community 10 - "Kotlin A2A Client"
Cohesion: 0.0
Nodes (21): A2aClient, log(), JsonRpcRequest, RpcParams, RpcConfiguration, SynthBundle, _per_category_price_stats(), _gen_product() (+13 more)

### Community 22 - "Kotlin Message Builder"
Cohesion: 0.0
Nodes (1): A2aMessageBuilder

### Community 20 - "Kotlin A2A Types"
Cohesion: 0.0
Nodes (7): Role, Part, TextPart, DataPart, Message, AgentCard, Skill

### Community 31 - "HTTP Client"
Cohesion: 0.0
Nodes (0): 

### Community 17 - "Kotlin Shopping Tools"
Cohesion: 0.0
Nodes (5): ShoppingTools, PaymentResult, Success, OtpRequired, Failure

### Community 29 - "Kotlin Chat Message"
Cohesion: 0.0
Nodes (2): SenderRole, ChatMessage

### Community 18 - "Kotlin DPC Types"
Cohesion: 0.0
Nodes (11): DpcRequest, Request, DcqlQuery, CredentialQuery, Meta, Claim, ClientMetadata, VpFormatsSupported (+3 more)

### Community 11 - "Kotlin Shopping Types"
Cohesion: 0.0
Nodes (23): JsonRpcResponse, ArtifactResult, Artifact, ArtifactPart, FullCartMandateWrapper, CartMandate, CartContents, PaymentRequestDetails (+15 more)

### Community 24 - "Kotlin Chat UI"
Cohesion: 0.0
Nodes (0): 

### Community 25 - "Kotlin ViewModel"
Cohesion: 0.0
Nodes (2): ChatUiState, ChatViewModel

### Community 32 - "Payment Models"
Cohesion: 0.0
Nodes (0): 

### Community 38 - "Task Management"
Cohesion: 0.0
Nodes (0): 

### Community 33 - "Error Handling"
Cohesion: 0.0
Nodes (0): 

### Community 39 - "Message Builder"
Cohesion: 0.0
Nodes (0): 

### Community 30 - "UI Components"
Cohesion: 0.0
Nodes (1): ExampleUnitTest

### Community 3 - "Go Server Main"
Cohesion: 0.0
Nodes (59): main(), AgentExecutor, AgentServer, NewAgentServer(), LoadAgentCard(), _get_data_parts(), BaseServerExecutor, AgentExecutor (+51 more)

### Community 34 - "Notification Service"
Cohesion: 0.0
Nodes (1): ContactAddress

### Community 9 - "Go Mandates"
Cohesion: 0.0
Nodes (18): IntentMandate, NewIntentMandate(), boolPtr(), CartContents, CartMandate, PaymentMandateContents, PaymentMandate, PaymentCurrencyAmount (+10 more)

### Community 16 - "Go A2A Types"
Cohesion: 0.0
Nodes (11): Role, Message, TaskState, TaskStatus, Artifact, Task, AgentCard, AgentCapabilities (+3 more)

### Community 2 - "A2A Protocol Types"
Cohesion: 0.0
Nodes (75): TextPart, DataPart, Part, A2AHelperError, RuntimeError, _client_for(), _resolve_url(), _stamp_identity() (+67 more)

### Community 5 - "Go Agent Executors"
Cohesion: 0.0
Nodes (31): BaseExecutor, NewBaseExecutor(), ToolFunc, ToolInfo, FunctionResolver, NewFunctionResolver(), containsIgnoreCase(), MessageBuilder (+23 more)

### Community 26 - "Go JSON-RPC"
Cohesion: 0.0
Nodes (3): JSONRPCRequest, JSONRPCResponse, JSONRPCError

### Community 12 - "Demo Code"
Cohesion: 0.0
Nodes (21): banner(), show(), main(), Demo: Merchant-on-File (Mode 2) from the Shopper's perspective.  Runs without A2, get_on_file_methods(), resolve_alias_to_psp_ref(), Returns agent-layer-safe descriptions of saved methods for this user.      Filte, Merchant-internal helper: alias shown to agent -> PSP reference.      For the SQ (+13 more)

### Community 0 - "Python A2A Helpers"
Cohesion: 0.0
Nodes (111): Pure-python helpers for invoking the AP2 sample agents over A2A.  These helpers, Raised when an A2A round-trip cannot be parsed into a useful result., One ``PaymentRemoteA2aClient`` per ``base_url`` for the process., Add the shopping-agent identity (and optional ``tool_hint``) to every     outbou, Flatten every DataPart payload off a Task.      Walks three places, in priority, Ask the merchant agent for matching products → returns CartMandates.      Return, Ask the merchant agent to recompute totals + bind shipping address.      Returns, Look up the customer's saved (merchant-on-file) payment methods.      Returns a (+103 more)

### Community 40 - "Credentials"
Cohesion: 0.0
Nodes (0): 

### Community 13 - "Key Management"
Cohesion: 0.0
Nodes (18): _write_private_pem(), ensure_rsa_key(), ensure_ec_key(), load_private_key(), export_public_pem(), Key generation + loading helpers (idempotent)., Generate an RSA private key at ``path`` if it doesn't exist., Generate an EC private key at ``path`` if it doesn't exist. (+10 more)

### Community 7 - "Crypto Primitives"
Cohesion: 0.0
Nodes (39): Real cryptographic primitives for the Shopping Agent.  Provides ECDSA P-256 sign, _handle_payment_mandate(), _emit_challenge(), _authorize_and_complete(), _create_payment_receipt(), _maybe_get_credentials_provider_client(), _create_text_parts(), Handles the initiation of a payment.    The adapter is selected from the inbou (+31 more)

### Community 15 - "Auth Tokens"
Cohesion: 0.0
Nodes (14): _jwks_client(), token_hash(), _identity_hash(), _validate_jwt(), _load_static_tokens(), auth_mode(), check_bearer(), Bearer-token auth for the streamable-HTTP transport.  Two modes, selected at run (+6 more)

### Community 8 - "Catalog & Products"
Cohesion: 0.0
Nodes (35): ProductSummary, ProductDetail, register(), _row_to_summary(), register(), Catalog tools — pure SQLite reads against ``pharmacy_data``.  Tools that the LLM, register(), _load() (+27 more)

### Community 14 - "Session Storage"
Cohesion: 0.0
Nodes (18): _ensure_table(), _conn(), _now(), get_or_create(), update(), set_cart_mandate(), set_chosen_payment(), set_payment_mandate() (+10 more)

### Community 41 - "Tool Registry"
Cohesion: 0.0
Nodes (0): 

### Community 42 - "Request Handlers"
Cohesion: 0.0
Nodes (0): 

### Community 19 - "Storage & Cache"
Cohesion: 0.0
Nodes (8): get_cart_mandate(), set_cart_mandate(), set_risk_data(), get_risk_data(), Get a cart mandate by cart ID., Set a cart mandate by cart ID., Set risk data by context ID., Get risk data by context ID.

### Community 43 - "Response Formatters"
Cohesion: 0.0
Nodes (0): 

### Community 21 - "Agent Entry Points"
Cohesion: 0.0
Nodes (0): 

### Community 4 - "Mandate Signing"
Cohesion: 0.0
Nodes (56): get_mandate_signer(), set_mandate_signer(), sign_mandates_on_user_device(), _generate_cart_mandate_hash(), _generate_payment_mandate_hash(), canonical_json(), JSON canonicalization for deterministic hashing.  Implements RFC 8785 (JSON Cano, Serialize a JSON-compatible value to canonical UTF-8 bytes.      - Object keys a (+48 more)

### Community 44 - "A2A Protocol"
Cohesion: 0.0
Nodes (1): Load the persisted keypair from disk, generating one on first run.          The

### Community 45 - "Configuration"
Cohesion: 0.0
Nodes (1): SHA-256 hex digest of the canonical JSON form of `obj`.          Accepts either

### Community 46 - "Logging"
Cohesion: 0.0
Nodes (1): Verify a compact authorization string; raise on failure.          Returns the pa

### Community 47 - "Database"
Cohesion: 0.0
Nodes (0): 

### Community 48 - "Serialization"
Cohesion: 0.0
Nodes (0): 

### Community 49 - "Validation"
Cohesion: 0.0
Nodes (1): Agent Payments Protocol (AP2)

### Community 50 - "Middleware"
Cohesion: 0.0
Nodes (1): A2A Protocol

### Community 51 - "Router"
Cohesion: 0.0
Nodes (1): MCP Protocol

### Community 52 - "Controller"
Cohesion: 0.0
Nodes (1): x402

### Community 53 - "Service Layer"
Cohesion: 0.0
Nodes (1): Universal Checkout Protocol (UCP)

### Community 54 - "Repository"
Cohesion: 0.0
Nodes (1): Verifiable Digital Credentials (VDCs)

### Community 55 - "Domain Models"
Cohesion: 0.0
Nodes (1): CartMandate

### Community 56 - "Value Objects"
Cohesion: 0.0
Nodes (1): IntentMandate

### Community 57 - "Events"
Cohesion: 0.0
Nodes (1): PaymentMandate

### Community 58 - "Handlers"
Cohesion: 0.0
Nodes (1): Shopping Agent

### Community 59 - "Converters"
Cohesion: 0.0
Nodes (1): Credentials Provider (CP)

### Community 60 - "Formatters"
Cohesion: 0.0
Nodes (1): Merchant Payment Processor (MPP)

### Community 61 - "Parsers"
Cohesion: 0.0
Nodes (1): Merchant Endpoint (ME)

### Community 62 - "Factories"
Cohesion: 0.0
Nodes (1): Network and Issuer

### Community 63 - "Builders"
Cohesion: 0.0
Nodes (1): Human Present Transaction

### Community 64 - "Decorators"
Cohesion: 0.0
Nodes (1): Human Not Present Transaction

### Community 65 - "Plugins"
Cohesion: 0.0
Nodes (1): Card Payment

### Community 66 - "Extensions"
Cohesion: 0.0
Nodes (1): DPAN (Digital PAN)

### Community 67 - "Mixins"
Cohesion: 0.0
Nodes (1): Digital Payment Credentials (DPC)

### Community 68 - "Interfaces"
Cohesion: 0.0
Nodes (1): x402 Payment

### Community 69 - "Abstract Classes"
Cohesion: 0.0
Nodes (1): OTP Challenge

### Community 70 - "Base Classes"
Cohesion: 0.0
Nodes (1): 3D Secure

### Community 71 - "Helper Functions"
Cohesion: 0.0
Nodes (1): Agent Card

### Community 72 - "Constants"
Cohesion: 0.0
Nodes (1): search_catalog Skill

### Community 73 - "Enums"
Cohesion: 0.0
Nodes (1): MCP Gateway

### Community 74 - "Flags"
Cohesion: 0.0
Nodes (1): Adyen

### Community 75 - "Config"
Cohesion: 0.0
Nodes (1): Privacy and Security (AP2)

### Community 76 - "Options"
Cohesion: 0.0
Nodes (1): Core Concepts (AP2)

### Community 77 - "Settings"
Cohesion: 0.0
Nodes (1): Life of a Transaction (AP2)

### Community 78 - "Parameters"
Cohesion: 0.0
Nodes (1): A2A Extension

### Community 79 - "Arguments"
Cohesion: 0.0
Nodes (1): AP2 Mandates Extension

### Community 80 - "Inputs"
Cohesion: 0.0
Nodes (1): Checkout Object (UCP)

### Community 81 - "Outputs"
Cohesion: 0.0
Nodes (1): CheckoutMandate (UCP)

### Community 82 - "Results"
Cohesion: 0.0
Nodes (1): Python Samples

### Community 83 - "Returns"
Cohesion: 0.0
Nodes (1): Go Samples

### Community 84 - "Responses"
Cohesion: 0.0
Nodes (1): Android Samples

## Knowledge Gaps
- **246 isolated node(s):** `Adyen zero-auth CLI — provision a real ``storedPaymentMethodId``.  Usage:      p`, `Assemble Adyen zero-auth request body.      Notes:       * ``shopperInteraction=`, `Pull the new stored-payment-method id from the Adyen response.      Adyen return`, `Pick which ``merchant_on_file_methods`` row to patch.      Priority:       1. ro`, `Tiny launcher for the three AP2 backend agents.  Usage:     python ops/run_agent` (+241 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Data Models`** (1 nodes): `build.gradle.kts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Utils`** (1 nodes): `settings.gradle.kts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Webhooks`** (1 nodes): `build.gradle.kts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `HTTP Client`** (2 nodes): `DpcHelper.kt`, `constructDPCRequest()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Payment Models`** (2 nodes): `SettingsScreen.kt`, `SettingsScreen()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Task Management`** (1 nodes): `Color.kt`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Error Handling`** (2 nodes): `Theme.kt`, `A2achatassistantTheme()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Message Builder`** (1 nodes): `Type.kt`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Notification Service`** (2 nodes): `contact_address.go`, `ContactAddress`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Credentials`** (1 nodes): `system_utils.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Tool Registry`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Request Handlers`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Response Formatters`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `A2A Protocol`** (1 nodes): `Load the persisted keypair from disk, generating one on first run.          The`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Configuration`** (1 nodes): `SHA-256 hex digest of the canonical JSON form of `obj`.          Accepts either`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Logging`** (1 nodes): `Verify a compact authorization string; raise on failure.          Returns the pa`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Database`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Serialization`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Validation`** (1 nodes): `Agent Payments Protocol (AP2)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Middleware`** (1 nodes): `A2A Protocol`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Router`** (1 nodes): `MCP Protocol`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Controller`** (1 nodes): `x402`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Service Layer`** (1 nodes): `Universal Checkout Protocol (UCP)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Repository`** (1 nodes): `Verifiable Digital Credentials (VDCs)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Domain Models`** (1 nodes): `CartMandate`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Value Objects`** (1 nodes): `IntentMandate`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Events`** (1 nodes): `PaymentMandate`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Handlers`** (1 nodes): `Shopping Agent`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Converters`** (1 nodes): `Credentials Provider (CP)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Formatters`** (1 nodes): `Merchant Payment Processor (MPP)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Parsers`** (1 nodes): `Merchant Endpoint (ME)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Factories`** (1 nodes): `Network and Issuer`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Builders`** (1 nodes): `Human Present Transaction`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Decorators`** (1 nodes): `Human Not Present Transaction`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Plugins`** (1 nodes): `Card Payment`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Extensions`** (1 nodes): `DPAN (Digital PAN)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Mixins`** (1 nodes): `Digital Payment Credentials (DPC)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Interfaces`** (1 nodes): `x402 Payment`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Abstract Classes`** (1 nodes): `OTP Challenge`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Base Classes`** (1 nodes): `3D Secure`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Helper Functions`** (1 nodes): `Agent Card`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Constants`** (1 nodes): `search_catalog Skill`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Enums`** (1 nodes): `MCP Gateway`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Flags`** (1 nodes): `Adyen`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Config`** (1 nodes): `Privacy and Security (AP2)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Options`** (1 nodes): `Core Concepts (AP2)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Settings`** (1 nodes): `Life of a Transaction (AP2)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Parameters`** (1 nodes): `A2A Extension`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Arguments`** (1 nodes): `AP2 Mandates Extension`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Inputs`** (1 nodes): `Checkout Object (UCP)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Outputs`** (1 nodes): `CheckoutMandate (UCP)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Results`** (1 nodes): `Python Samples`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Returns`** (1 nodes): `Go Samples`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Responses`** (1 nodes): `Android Samples`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `build()` connect `A2A Protocol Types` to `Catalog & Products`, `Kotlin A2A Client`, `Go Server Main`, `Go Agent Executors`?**
  _High betweenness centrality (0.111) - this node is a cross-community bridge._
- **Why does `PaymentMandate` connect `Python A2A Helpers` to `Adyen Payment Integration`, `A2A Protocol Types`, `Go Server Main`, `Mandate Signing`, `Crypto Primitives`?**
  _High betweenness centrality (0.109) - this node is a cross-community bridge._
- **Why does `BaseServerExecutor` connect `Go Server Main` to `Python A2A Helpers`, `Adyen Payment Integration`, `A2A Protocol Types`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Are the 83 inferred relationships involving `PaymentMandate` (e.g. with `A2AHelperError` and `Pure-python helpers for invoking the AP2 sample agents over A2A.  These helpers`) actually correct?**
  _`PaymentMandate` has 83 INFERRED edges - model-reasoned connections that need verification._
- **Are the 73 inferred relationships involving `A2aMessageBuilder` (e.g. with `A2AHelperError` and `merchant_find_products()`) actually correct?**
  _`A2aMessageBuilder` has 73 INFERRED edges - model-reasoned connections that need verification._
- **Are the 60 inferred relationships involving `ContactAddress` (e.g. with `A2AHelperError` and `Pure-python helpers for invoking the AP2 sample agents over A2A.  These helpers`) actually correct?**
  _`ContactAddress` has 60 INFERRED edges - model-reasoned connections that need verification._
- **Are the 47 inferred relationships involving `CartMandate` (e.g. with `A2AHelperError` and `Pure-python helpers for invoking the AP2 sample agents over A2A.  These helpers`) actually correct?**
  _`CartMandate` has 47 INFERRED edges - model-reasoned connections that need verification._