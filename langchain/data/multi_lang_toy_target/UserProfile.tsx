// Minimal TSX fixture -- exists to prove the tsx grammar (JSX-in-TypeScript)
// parses correctly through the same javascript-tags-query override app.ts
// uses, not to model a second vulnerability.
function renderGreeting(name: string) {
    return greet(name);
}

function greet(name: string): string {
    return "Hello, " + name;
}

function UserProfile(props: { name: string }) {
    return <div>{renderGreeting(props.name)}</div>;
}
