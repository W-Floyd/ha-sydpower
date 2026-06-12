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