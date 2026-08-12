# go-fAST JS Deconstruction Tool

This program demonstrates how to use the [go-fAST](https://github.com/T14Raptor/go-fAST) library to deconstruct JavaScript files into component functions and reconstruct them with modifications.

## Features

- **Parse JavaScript**: Convert any JavaScript source code into an AST (Abstract Syntax Tree)
- **Extract Functions**: Identify and extract all functions including:
  - Function declarations
  - Arrow functions (anonymous and named)
  - Method definitions (regular, getters, setters)
  - Class methods
- **Transform Functions**: Apply custom modifications to extracted functions
- **Reconstruct Code**: Generate modified JavaScript from the transformed AST
- **File I/O**: Read from and write to JavaScript files

## Dependencies

```go
require github.com/t14raptor/go-fast v0.0.0
```

Install with:
```bash
go get github.com/t14raptor/go-fast
```

## Usage

### Basic Processing

```go
// Create a processor for JavaScript source
processor, err := NewJSProcessor(`
function add(a, b) {
    return a + b;
}
const multiply = (x, y) => x * y;
`)

// Get all extracted functions
funcs := processor.GetFunctions()

// Process a specific function
processor.ProcessFunction("add", func(fn *ExtractedFunction) (*ExtractedFunction, error) {
    // Modify the function here
    return fn, nil
})

// Reconstruct the code
output := processor.Reconstruct()
```

### File Processing

```go
// Load a JavaScript file
processor, err := NewFileProcessor("input.js")

// Process functions
processor.GetProcessor().ProcessFunction("myFunction", func(fn *ExtractedFunction) (*ExtractedFunction, error) {
    // Modify the function
    return fn, nil
})

// Save the processed file
processor.SaveAs("output.js")
```

### Deconstruct and Analyze

```go
program, extractor, err := Deconstruct(javascriptSource)

// List all functions
for _, fn := range extractor.GetFunctions() {
    fmt.Printf("Name: %s, Type: %s, Range: %d-%d\n", 
        fn.Name, fn.FunctionType, fn.StartIdx, fn.EndIdx)
}
```

## API Reference

### Main Types

- **`JSProcessor`**: Main processor for JavaScript source code
- **`FunctionExtractor`**: Extracts functions from parsed AST
- **`ExtractedFunction`**: Represents an extracted function
- **`FileProcessor`**: Handles file I/O operations

### Key Functions

- `NewJSProcessor(source string) (*JSProcessor, error)`: Create a new processor
- `NewFileProcessor(filename string) (*FileProcessor, error)`: Load a file
- `Deconstruct(source string) (*ast.Program, *FunctionExtractor, error)`: Parse and extract
- `ProcessFunction(name string, transform func) error`: Apply transformations
- `Reconstruct() string`: Generate the final JavaScript code

## Examples

See `main.go` for complete working examples demonstrating:
- Function extraction from various function types
- Processing and modifying functions
- File I/O operations
- AST manipulation techniques

## Requirements

- Go 1.21 or higher
- github.com/t14raptor/go-fast library
## Rebuilding the product catalog

`extract_catalog.py` regenerates `sydpower/product_catalog.json` from a BrightEMS
XAPK. The catalog is *not* embedded in the app: BrightEMS is a uni-app front end
over a uniCloud (aliyun) backend, and the products, categories and per-product
feature definitions all come from one cloud function.

```bash
pip install jsbeautifier
python extract_catalog.py --xapk BrightEMS_1.6.6_APKPure.xapk
```

Stages run in order and can be stopped at any point with `--stage`:

| Stage | What it does |
| --- | --- |
| `unpack` | XAPK → base APK → the uni-app bundle (skips `config.*` splits) |
| `beautify` | Beautifies the bundle into `build/js/`; `app-service.js` goes from 1 line to ~60,000 |
| `config` | Reads `spaceId`, `clientSecret` and endpoint **out of the beautified source** |
| `fetch` | Anonymous auth, then the public catalog endpoints, caching raw JSON in `build/api/` |
| `build` | Assembles the catalog from the cache — no network |

`--stage beautify` is the one to use for reading the app. Searching the shipped
bundle directly is a trap: it is a single ~2 MB line, and non-trivial regexes
backtrack until they appear to hang.

Responses are cached because the backend resets connections under repeated calls.
Re-run `--stage build` freely; add `--refresh` to re-fetch.

### Protocol notes

Worked out from the beautified bundle rather than guessed:

- One cloud function, `router`. The action goes in `$url` with the payload nested
  under `data` (vk-unicloud convention).
- Requests are signed with **HMAC-MD5** over the truthy parameters sorted by key
  and joined as `k=v&k=v`, in the `x-serverless-sign` header.
- Even the `pub/` (public) actions need an anonymous access token, obtained via
  `serverless.auth.user.anonymousAuthorize`. Without it the router replies
  `param_token_required`.
- `--locale` is forwarded in `x-client-info`; the backend localises feature
  names. The previously shipped catalog had French labels because of this.

### Outputs

- `sydpower/product_catalog.json` — categories and products only, ~43 KB, shipped
  in the wheel.
- `reference/product_catalog.full.json` — adds `features`, ~750 KB, kept out of
  the package. Useful for reference, but do not derive sensors from its indices:
  a child's `input_index` is a sub-index within its parent, not a register
  number, which has produced wrong readings before.

`brand_id` is deliberately dropped. The largest group is 省油灯(中性通用) —
"neutral/universal", the OEM's white-label bucket — and resellers such as AFERIY
and FOSSiBOT do not appear at all. `product_name` is the useful identity: it
holds the OEM model code, e.g. `P210-A0E01` for an AFERIY P210.

### Authenticated endpoints

Everything under `client/device/` rejects an anonymous token with
`token校验未通过` ("token verification failed"); only the `client/product/pub/`
actions are reachable without signing in. Two useful payloads sit behind that:

| Action | Contains |
| --- | --- |
| `client/device/kh/getFirmwareUpgradeHint` | `AC_standby_time_list`, the firmware gate table, plus `product_version_list` |
| `client/device/faultCode.getList` | Fault code descriptions |

Pass a signed-in user token to fetch and cache them:

```bash
BRIGHTEMS_TOKEN=... python extract_catalog.py --xapk app.xapk
# or: python extract_catalog.py --xapk app.xapk --token ...
```

Without one the script logs which actions it skipped and carries on; the catalog
simply has no `firmware_gates` section, and the gate is then a no-op.

### The firmware gate

Some product and panel-version combinations cannot honour every option the
catalog lists. For the AC no-load standby timer the app drops the zero ("never
turn off") option when a rule matches:

```
rule.product_name == productInfo.name
  and 10 * float(rule.panel_version) == lowByte(holding[50])
```

Register 50 is the panel firmware version — the app's constant is
`Panel_Version`, though it posts the same register to its backend as
`DC_version`. Versions are tenths, so a register value of 29 is v2.9. The four
version registers are 47 (AC), 48 (BMS), 49 (PV) and 50 (panel).

### Signing in

`--login` obtains a user token for the authenticated actions:

```bash
python extract_catalog.py --xapk app.xapk --login
```

It reads `BRIGHTEMS_USER` and `BRIGHTEMS_PASSWORD` from the environment, or
prompts for anything missing. The password is deliberately **not** accepted as a
command-line argument: argv is visible to other processes on the machine and ends
up in shell history. It is read with `getpass`, never echoed, and never logged.

The resulting token is cached in `build/api/user_token.json` with mode 600 and
reused on later runs; `--refresh` obtains a fresh one. `build/` is gitignored, so
neither the token nor the unpacked app is committed.

Note the missing `client/` prefix on user-centre actions: `client/user/pub/login`
returns `404 not found`, while `user/pub/login` works. The app's own actions do
carry the prefix.

There are two login paths, and which applies depends on the account:

- **Username** — `user/pub/login` with `{username, password}`. `username` is
  mandatory; passing an email in that field returns "user does not exist", and
  supplying `email` instead returns "username cannot be empty".
- **Email** — password login is not available. `user/pub/loginByEmail` requires an
  emailed verification code (`{email, code}`); any password sent with it is
  ignored and it answers "verification code wrong or expired". The script
  therefore calls `user/pub/sendEmailCode` and prompts for the code, or reads
  `BRIGHTEMS_CODE` if you would rather not be prompted.


### Caching and re-use

The user token is cached at `build/api/user_token.json` with mode 600 and reused
automatically, so signing in is a one-off. `--refresh` deliberately does not
invalidate it — that flag re-fetches API payloads, and discarding the token would
mean another emailed code. Use `--relogin` to force a fresh sign-in.

Two tokens are in play and they are **not** interchangeable:

| Token | Carried in | Identifies |
| --- | --- | --- |
| anonymous access token | request body `token`, `x-basement-token` | the client, to the uniCloud gateway |
| uni-id user token | `x-client-token` header, and `uniIdToken` in the args | the signed-in user, to the router |

Substituting the user token for the gateway's returns
`GATEWAY_INVALID_TOKEN / session_expired`.

### What the authenticated endpoints contain

`getFirmwareUpgradeHint` wraps its payload under `data`:

- `AC_standby_time_list` — the setting gate table. Currently one rule, for
  `POWER-0504` on panel version 1.7.
- `product_version_list` — a second gate, matched on `ac_version`, used for the
  firmware upgrade prompt.
- `hint`, `tutorial_url`, `tutorial_title`, `enable` — upgrade prompt strings.

`faultCode.getList` returns five fault groups, each naming the registers it reads
in `byte_list` and decoding them bit by bit in `bit_list`:

| Group | Registers | Named bits |
| --- | --- | --- |
| AC FaultCode | 43 | 10 |
| PV FaultCode | 45 | 6 |
| BMS AFE Status | 47 | 9 |
| BMS USER Status | 48 | 6 |
| Panel FaultCode | 50, 51 | 11 |

These are **input**-bank registers. The numbers overlap the firmware versions at
holding 47-50, which are a different address space: the app reads versions from
`holdingRegister` and faults from `inputRegister`. Conflating them would report a
firmware version as a fault bitfield.

For a two-register group the *second* register supplies bits 0-15 and the first
bits 16-31, so bit 17 of Panel FaultCode is bit 1 of register 50.

Only bits carrying a message count as faults. A healthy device here reads 0x3000
in register 47 and 0x4000 in register 48, and none of those bits are named — the
app ignores unnamed bits, so those are status flags rather than problems.

Fetched without a `product_id`, which returns every group along with its name;
the per-product response omits `name`. Groups are therefore not filtered per
product, so another product family could in principle use different registers.

25 of the 42 messages are still Chinese despite `--locale en`; the backend's
translations are incomplete, and there is nothing to be done about that here.
