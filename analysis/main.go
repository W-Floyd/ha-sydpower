package main

import (
	"fmt"
	"log"
	"os"

	"github.com/t14raptor/go-fast/ast"
	"github.com/t14raptor/go-fast/generator"
	"github.com/t14raptor/go-fast/parser"
)

// JSProcessor is the main struct for processing JavaScript files
type JSProcessor struct {
	source        string
	program       *ast.Program
	extractor     *FunctionExtractor
	modifiedCount int
}

// NewJSProcessor creates a new JSProcessor for a given source file
func NewJSProcessor(source string) (*JSProcessor, error) {
	program, extractor, err := Deconstruct(source)
	if err != nil {
		return nil, err
	}

	return &JSProcessor{
		source:        source,
		program:       program,
		extractor:     extractor,
		modifiedCount: 0,
	}, nil
}

// Deconstruct parses JS source and extracts all functions
func Deconstruct(jsSource string) (*ast.Program, *FunctionExtractor, error) {
	program, err := parser.ParseFile(jsSource)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to parse JS: %w", err)
	}

	extractor := NewFunctionExtractor()
	extractor.Extract(program)

	return program, extractor, nil
}

// GetExtractor returns the function extractor
func (jp *JSProcessor) GetExtractor() *FunctionExtractor {
	return jp.extractor
}

// GetFunctions returns all extracted functions
func (jp *JSProcessor) GetFunctions() []ExtractedFunction {
	return jp.extractor.GetFunctions()
}

// FunctionCount returns the number of extracted functions
func (jp *JSProcessor) FunctionCount() int {
	return len(jp.extractor.GetFunctions())
}

// ProcessFunction applies a transformation to a named function
func (jp *JSProcessor) ProcessFunction(name string, transform func(*ExtractedFunction) (*ExtractedFunction, error)) error {
	for i := range jp.extractor.functions {
		if jp.extractor.functions[i].Name == name {
			modified, err := transform(&jp.extractor.functions[i])
			if err != nil {
				return err
			}
			jp.extractor.functions[i] = *modified
			jp.modifiedCount++
			return nil
		}
	}
	return fmt.Errorf("function not found: %s", name)
}

// Reconstruct generates the final JavaScript source with all modifications
func (jp *JSProcessor) Reconstruct() string {
	return generator.Generate(jp.program)
}

// PrintFunctionSummary prints information about all extracted functions
func (jp *JSProcessor) PrintFunctionSummary() {
	functions := jp.GetFunctions()
	fmt.Printf("Found %d functions:\n", len(functions))
	fmt.Println("---")
	for i, fn := range functions {
		fmt.Printf("%d. Name: %s\n", i+1, fn.Name)
		fmt.Printf("   Type: %s\n", fn.FunctionType)
		fmt.Printf("   Range: %d-%d\n", fn.StartIdx, fn.EndIdx)
		fmt.Println()
	}
}

// GetOriginalSource returns the original source code
func (jp *JSProcessor) GetOriginalSource() string {
	return jp.source
}

// FunctionExtractor is responsible for extracting functions from a parsed JS AST
type FunctionExtractor struct {
	functions []ExtractedFunction
}

// ExtractedFunction represents a single function extracted from the JS file
type ExtractedFunction struct {
	Name         string
	StartIdx     ast.Idx
	EndIdx       ast.Idx
	FunctionType string // "function_declaration", "arrow_function", "method", "setter", "getter"
	Node         ast.VisitableNode
}

// NewFunctionExtractor creates a new FunctionExtractor instance
func NewFunctionExtractor() *FunctionExtractor {
	return &FunctionExtractor{
		functions: make([]ExtractedFunction, 0),
	}
}

// Extract scans the AST and extracts all functions
func (fe *FunctionExtractor) Extract(node ast.VisitableNode) {
	extractor := &functionVisitor{extractor: fe}
	node.VisitWith(extractor)
}

// GetFunctions returns a slice of all extracted functions
func (fe *FunctionExtractor) GetFunctions() []ExtractedFunction {
	return fe.functions
}

// FindFunctionByName returns the first function with the given name
func (fe *FunctionExtractor) FindFunctionByName(name string) *ExtractedFunction {
	for i := range fe.functions {
		if fe.functions[i].Name == name {
			return &fe.functions[i]
		}
	}
	return nil
}

// functionVisitor implements the AST visitor pattern to find functions
type functionVisitor struct {
	extractor   *FunctionExtractor
	inClass     bool
	inObjectLit bool
	className   string
	objName     string
}

func (v *functionVisitor) VisitFunctionDeclaration(n *ast.FunctionDeclaration) {
	name := ""
	if n.Function.Name != nil {
		name = n.Function.Name.Name
	}

	extracted := ExtractedFunction{
		Name:         name,
		StartIdx:     n.Function.Function,
		EndIdx:       n.Function.Idx1(),
		FunctionType: "function_declaration",
		Node:         n.Function,
	}

	v.extractor.functions = append(v.extractor.functions, extracted)
}

func (v *functionVisitor) VisitArrowFunctionLiteral(n *ast.ArrowFunctionLiteral) {
	name := "<anonymous>"
	if v.inObjectLit {
		name = fmt.Sprintf("%s.%s", v.objName, "<anonymous>")
	}
	v.extractor.functions = append(v.extractor.functions, ExtractedFunction{
		Name:         name,
		StartIdx:     n.Start,
		EndIdx:       n.Body.Idx1(),
		FunctionType: "arrow_function",
		Node:         n,
	})
}

func (v *functionVisitor) VisitMethodDefinition(n *ast.MethodDefinition) {
	methodType := "method"
	if n.Kind == ast.PropertyKindGet {
		methodType = "getter"
	} else if n.Kind == ast.PropertyKindSet {
		methodType = "setter"
	}

	name := ""
	if v.className != "" {
		name = fmt.Sprintf("%s.%s", v.className, n.Key.String())
	} else {
		name = fmt.Sprintf("<anonymous>.%s", n.Key.String())
	}

	v.extractor.functions = append(v.extractor.functions, ExtractedFunction{
		Name:         name,
		StartIdx:     n.Body.Function.Function,
		EndIdx:       n.Body.Idx1(),
		FunctionType: methodType,
		Node:         n.Body,
	})
}

func (v *functionVisitor) VisitBlockStatement(n *ast.BlockStatement) {
	for _, stmt := range n.List {
		stmt.Stmt.VisitWith(v)
	}
}

func (v *functionVisitor) VisitProgram(n *ast.Program) {
	for _, stmt := range n.Body {
		stmt.Stmt.VisitWith(v)
	}
}

func (v *functionVisitor) VisitObjectLiteral(n *ast.ObjectLiteral) {
	oldInObject := v.inObjectLit
	oldObjName := v.objName

	v.inObjectLit = true
	v.objName = "<anonymous>"

	for _, prop := range n.Value {
		prop.Prop.VisitWith(v)
	}

	v.inObjectLit = oldInObject
	v.objName = oldObjName
}

func (v *functionVisitor) VisitClassLiteral(n *ast.ClassLiteral) {
	oldInClass := v.inClass
	oldClassName := v.className

	v.inClass = true
	v.className = "<anonymous>"
	if n.Name != nil {
		v.className = n.Name.Name
	}

	for _, element := range n.Body {
		if methodDef, ok := element.Element.(*ast.MethodDefinition); ok {
			v.extractFunction(methodDef)
		}
	}

	v.inClass = oldInClass
	v.className = oldClassName
}

func (v *functionVisitor) extractFunction(methodDef *ast.MethodDefinition) {
	methodType := "method"
	if methodDef.Kind == ast.PropertyKindGet {
		methodType = "getter"
	} else if methodDef.Kind == ast.PropertyKindSet {
		methodType = "setter"
	}

	name := ""
	if v.inClass {
		name = fmt.Sprintf("%s.%s", v.className, methodDef.Key.String())
	}

	v.extractor.functions = append(v.extractor.functions, ExtractedFunction{
		Name:         name,
		StartIdx:     methodDef.Body.Function.Function,
		EndIdx:       methodDef.Body.Idx1(),
		FunctionType: methodType,
		Node:         methodDef.Body,
	})
}

func (v *functionVisitor) VisitVariableDeclaration(n *ast.VariableDeclaration) {
	for _, decl := range n.List {
		if decl.Initializer != nil {
			if arrow, ok := decl.Initializer.Expr.(*ast.ArrowFunctionLiteral); ok {
				name := ""
				if ident, ok := decl.Target.Target.(*ast.Identifier); ok {
					name = ident.Name
				}
				v.extractor.functions = append(v.extractor.functions, ExtractedFunction{
					Name:         name,
					StartIdx:     arrow.Start,
					EndIdx:       arrow.Body.Idx1(),
					FunctionType: "arrow_function",
					Node:         arrow,
				})
			}
		}
	}
}

// ASTModifier provides utilities for modifying AST nodes
type ASTModifier struct {
	functionMap map[string]*ast.FunctionLiteral
}

// NewASTModifier creates a new ASTModifier
func NewASTModifier() *ASTModifier {
	return &ASTModifier{
		functionMap: make(map[string]*ast.FunctionLiteral),
	}
}

// RegisterFunction adds a function to the modifier's registry
func (am *ASTModifier) RegisterFunction(name string, node *ast.FunctionLiteral) {
	am.functionMap[name] = node
}

// GetFunction returns a registered function by name
func (am *ASTModifier) GetFunction(name string) *ast.FunctionLiteral {
	return am.functionMap[name]
}

// ReplaceFunctionInAST replaces a function declaration in the program AST
func (am *ASTModifier) ReplaceFunctionInAST(program *ast.Program, oldName, newName string) *ast.Program {
	for i := range program.Body {
		if funcDecl, ok := program.Body[i].Stmt.(*ast.FunctionDeclaration); ok {
			if funcDecl.Function.Name != nil && funcDecl.Function.Name.Name == oldName {
				funcDecl.Function.Name.Name = newName
				break
			}
		}
	}
	return program
}

// FunctionTransformer allows transforming function nodes
type FunctionTransformer struct {
	visitor *functionTransformerVisitor
}

// NewFunctionTransformer creates a new FunctionTransformer
func NewFunctionTransformer() *FunctionTransformer {
	return &FunctionTransformer{
		visitor: &functionTransformerVisitor{},
	}
}

// TransformAll visits all function nodes and applies transformations
func (ft *FunctionTransformer) TransformAll(node ast.VisitableNode, transform func(ast.VisitableNode) ast.VisitableNode) {
	node.VisitWith(ft.visitor)
}

// functionTransformerVisitor implements the visitor pattern for transforming functions
type functionTransformerVisitor struct {
	visitedFuncs []ast.VisitableNode
}

func (v *functionTransformerVisitor) VisitFunctionDeclaration(n *ast.FunctionDeclaration) {
	v.visitedFuncs = append(v.visitedFuncs, n.Function)
}

func (v *functionTransformerVisitor) VisitArrowFunctionLiteral(n *ast.ArrowFunctionLiteral) {
	v.visitedFuncs = append(v.visitedFuncs, n)
}

func (v *functionTransformerVisitor) VisitMethodDefinition(n *ast.MethodDefinition) {
	v.visitedFuncs = append(v.visitedFuncs, n.Body)
}

func (v *functionTransformerVisitor) VisitProgram(n *ast.Program) {
	for _, stmt := range n.Body {
		stmt.Stmt.VisitWith(v)
	}
}

// FileProcessor handles reading and writing JS files
type FileProcessor struct {
	processor *JSProcessor
	filename  string
}

// NewFileProcessor creates a new FileProcessor for a JS file
func NewFileProcessor(filename string) (*FileProcessor, error) {
	content, err := os.ReadFile(filename)
	if err != nil {
		return nil, fmt.Errorf("failed to read file: %w", err)
	}

	processor, err := NewJSProcessor(string(content))
	if err != nil {
		return nil, fmt.Errorf("failed to process JS: %w", err)
	}

	return &FileProcessor{
		processor: processor,
		filename:  filename,
	}, nil
}

// Process applies modifications and saves the file
func (fp *FileProcessor) Process() error {
	processed := fp.processor.Reconstruct()
	return os.WriteFile(fp.filename, []byte(processed), 0644)
}

// SaveAs saves the processed file to a new location
func (fp *FileProcessor) SaveAs(newFilename string) error {
	processed := fp.processor.Reconstruct()
	return os.WriteFile(newFilename, []byte(processed), 0644)
}

// GetProcessor returns the underlying JSProcessor
func (fp *FileProcessor) GetProcessor() *JSProcessor {
	return fp.processor
}

// Main demonstrates the JS deconstruction and reconstruction capabilities
func main() {
	// Example JavaScript source code
	exampleJS := `// Example JavaScript file for deconstruction
function add(a, b) {
	return a + b;
}

const multiply = (x, y) => {
	return x * y;
};

const obj = {
	name: "example",
	greets: function() {
		return "Hello";
	},
	getter: function() {
		return this.name;
	}
};

class MyClass {
	constructor(value) {
		this.value = value;
	}

	getValue() {
		return this.value;
	}

	setValue(v) {
		this.value = v;
	}
}

async function fetchData(url) {
	const response = await fetch(url);
	return response.json();
}

function calculate(x) {
	if (x > 0) {
		return x * 2;
	} else {
		return 0;
	}
}`

	// Create a JSProcessor instance
	processor, err := NewJSProcessor(exampleJS)
	if err != nil {
		log.Fatalf("Failed to process JS: %v", err)
	}

	// Print summary of extracted functions
	processor.PrintFunctionSummary()

	// Process specific functions
	funcs := processor.GetFunctions()
	for _, fn := range funcs {
		if fn.Name == "add" {
			processor.ProcessFunction("add", func(funcObj *ExtractedFunction) (*ExtractedFunction, error) {
				fmt.Printf("\nProcessing function: %s\n", funcObj.Name)
				fmt.Printf("  Type: %s\n", funcObj.FunctionType)
				fmt.Printf("  Range: %d-%d\n", funcObj.StartIdx, funcObj.EndIdx)
				return funcObj, nil
			})
		}

		if fn.Name == "calculate" {
			processor.ProcessFunction("calculate", func(funcObj *ExtractedFunction) (*ExtractedFunction, error) {
				fmt.Printf("\nProcessing function: %s\n", funcObj.Name)
				fmt.Printf("  Type: %s\n", funcObj.FunctionType)
				fmt.Printf("  Range: %d-%d\n", funcObj.StartIdx, funcObj.EndIdx)
				return funcObj, nil
			})
		}
	}

	// Reconstruct the modified JavaScript
	reconstructed := processor.Reconstruct()
	fmt.Println("\n=== Reconstructed JavaScript ===")
	fmt.Println(reconstructed)
	fmt.Println("=== End of reconstructed JavaScript ===")

	// Demonstrate direct AST operations
	fmt.Println("\n=== Direct AST Operation Example ===")

	program, extractor, err := Deconstruct(`
function hello() {
	return "world";
}
`)
	if err != nil {
		log.Fatalf("Error: %v", err)
	}

	fmt.Printf("Parsed program with %d top-level statements\n", len(program.Body))

	for _, stmt := range program.Body {
		if decl, ok := stmt.Stmt.(*ast.FunctionDeclaration); ok {
			fmt.Printf("Found function: %s\n", decl.Function.Name.Name)
			fmt.Printf("Function starts at: %d, ends at: %d\n", decl.Function.Function, decl.Function.Idx1())
		}
	}

	// Process extracted functions
	if extractor != nil {
		for _, fn := range extractor.GetFunctions() {
			fmt.Printf("\nExtracted function: %s (type: %s)\n", fn.Name, fn.FunctionType)
			fmt.Printf("  Source range: %d-%d\n", fn.StartIdx, fn.EndIdx)

			if funcLit, ok := fn.Node.(*ast.FunctionLiteral); ok {
				fmt.Printf("  Generated code:\n%s\n", generator.Generate(funcLit))
			}
		}
	}

	// Demonstrate custom function modification
	fmt.Println("\n=== Custom Function Modification Demo ===")

	customJS := `
function processItem(item) {
	return item * 2;
}

function transformData(data) {
	return data.toUpperCase();
}
`

	customProcessor, err := NewJSProcessor(customJS)
	if err != nil {
		log.Fatalf("Error: %v", err)
	}

	// Process processItem function
	customProcessor.ProcessFunction("processItem", func(funcObj *ExtractedFunction) (*ExtractedFunction, error) {
		fmt.Printf("Processing function: %s\n", funcObj.Name)
		return funcObj, nil
	})

	// Process transformData function
	customProcessor.ProcessFunction("transformData", func(funcObj *ExtractedFunction) (*ExtractedFunction, error) {
		fmt.Printf("Processing function: %s\n", funcObj.Name)
		return funcObj, nil
	})

	// Reconstruct and display
	fmt.Println("\nModified code:")
	fmt.Println(customProcessor.Reconstruct())

	// Show file I/O example
	fmt.Println("\n=== File I/O Example ===")

	testJS := `
function testFunction() {
	console.log("This is a test");
}

const testConst = () => {
	return 42;
};
`

	// Write test file
	testFile := "/tmp/test.js"
	if err := os.WriteFile(testFile, []byte(testJS), 0644); err != nil {
		log.Printf("Warning: Could not write test file: %v", err)
	} else {
		fmt.Printf("Wrote test file to: %s\n", testFile)

		// Read it back
		content, err := os.ReadFile(testFile)
		if err != nil {
			log.Printf("Warning: Could not read test file: %v", err)
		} else {
			fmt.Printf("Read back %d bytes from: %s\n", len(content), testFile)

			// Process the file
			proc, err := NewJSProcessor(string(content))
			if err != nil {
				log.Printf("Warning: Could not process file: %v", err)
			} else {
				fmt.Printf("Successfully processed file with %d functions\n", proc.FunctionCount())
				proc.PrintFunctionSummary()
			}
		}
	}

	// Demonstrate FileProcessor for file operations
	fmt.Println("\n=== FileProcessor Example ===")

	fileProcessor, err := NewFileProcessor(testFile)
	if err != nil {
		log.Printf("Warning: Could not create FileProcessor: %v", err)
	} else {
		fmt.Printf("Created FileProcessor for: %s\n", fileProcessor.filename)
		fmt.Printf("Functions found: %d\n", fileProcessor.GetProcessor().FunctionCount())

		// Save to a new file
		outputFile := "/tmp/output_test.js"
		if err := fileProcessor.SaveAs(outputFile); err != nil {
			log.Printf("Warning: Could not save to %s: %v", outputFile, err)
		} else {
			fmt.Printf("Successfully saved to: %s\n", outputFile)
		}
	}
}
