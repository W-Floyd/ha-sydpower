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
