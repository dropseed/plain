# plain.react

**Build React frontends with Python views and server-side routing.**

- [Overview](#overview)
- [How it works](#how-it-works)
- [Views](#views)
    - [Shared props](#shared-props)
    - [Layouts](#layouts)
    - [Form handling](#form-handling)
- [Client-side API](#client-side-api)
    - [`createPlainApp`](#createplainapp)
    - [`usePage`](#usepage)
    - [`Link`](#link)
    - [`useForm`](#useform)
    - [`router`](#router)
- [React islands](#react-islands)
    - [Template tag](#template-tag)
    - [`mountIslands`](#mountislands)
- [Middleware](#middleware)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can use `plain.react` to build full React frontends while keeping all routing and data logic in Python. Instead of building a separate API, your Plain views return React components with props — the same pattern as a `TemplateView`, but with React instead of Jinja2.

```python
# app/views.py
from plain.react.views import ReactView


class UsersView(ReactView):
    component = "Users/Index"

    def get_props(self):
        return {
            "users": list(User.query.values("id", "name", "email")),
        }
```

```jsx
// app/react/pages/Users/Index.jsx
import { Link } from "./plain-react";

export default function Index({ users }) {
  return (
    <div>
      <h1>Users</h1>
      <ul>
        {users.map((user) => (
          <li key={user.id}>
            <Link href={`/users/${user.id}`}>{user.name}</Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

On the first page load, the server returns a full HTML page with the React app shell. On subsequent navigations, only JSON is exchanged and the client swaps components without a full page reload.

## How it works

The integration follows the Inertia.js protocol:

1. **Initial request** — the browser gets a full HTML page with a `<div id="app" data-page="...">` containing the serialized page data (component name, props, URL)
2. **SPA navigation** — when the user clicks a `<Link>`, the client sends a fetch request with an `X-Plain-React: true` header
3. **JSON response** — the server detects the header and returns just the page data as JSON instead of a full HTML document
4. **Client swap** — the client resolves the new component, renders it with the new props, and updates the browser history

This means you get SPA-like transitions with zero client-side routing. All URLs are defined in Python, all data loading happens in views, and React handles the rendering.

## Views

[`ReactView`](./views.py#ReactView) is the base class for all React views. Set the `component` attribute to the name of your React component and override `get_props()` to pass data.

```python
from plain.react.views import ReactView


class DashboardView(ReactView):
    component = "Dashboard"

    def get_props(self):
        return {
            "stats": get_dashboard_stats(),
            "recent_activity": get_recent_activity(),
        }
```

The `component` string maps to a file in your `app/react/pages/` directory. For example, `"Dashboard"` resolves to `pages/Dashboard.jsx` and `"Users/Index"` resolves to `pages/Users/Index.jsx`.

For POST and other methods, override the corresponding method and call `self.render()`:

```python
class CreateUserView(ReactView):
    component = "Users/Create"

    def get_props(self):
        return {"roles": list(Role.query.values("id", "name"))}

    def post(self):
        form = UserForm(self.request.data)
        if form.is_valid():
            form.save()
            return RedirectResponse("/users")
        return self.render({"roles": list(Role.query.values("id", "name")), "errors": form.errors})
```

### Shared props

Override `get_shared_props()` in a base view class to pass data to every page — things like the authenticated user, flash messages, or app-wide config.

```python
class AppView(ReactView):
    def get_shared_props(self):
        return {
            "auth": {"user": get_user_data(self.request)},
        }


class DashboardView(AppView):
    component = "Dashboard"

    def get_props(self):
        return {"stats": get_dashboard_stats()}
```

Shared props are merged with page-specific props, so `Dashboard` receives both `auth` and `stats`.

### Layouts

Set the `layout` attribute to wrap pages in a shared layout component:

```python
class AppView(ReactView):
    layout = "AppLayout"
```

The layout component receives the page as its `children`:

```jsx
// app/react/pages/AppLayout.jsx
export default function AppLayout({ children }) {
  return (
    <div>
      <nav>...</nav>
      <main>{children}</main>
    </div>
  );
}
```

### Form handling

The client-side `useForm` hook pairs with standard view methods. A typical create/edit pattern:

```python
class EditUserView(ReactView):
    component = "Users/Edit"

    def get_props(self):
        user = User.query.get(pk=self.url.kwargs["pk"])
        return {"user": {"name": user.name, "email": user.email}}

    def post(self):
        user = User.query.get(pk=self.url.kwargs["pk"])
        form = UserForm(self.request.data, instance=user)
        if form.is_valid():
            form.save()
            return RedirectResponse(f"/users/{user.pk}")
        return self.render({
            "user": {"name": user.name, "email": user.email},
            "errors": form.errors,
        })
```

## Client-side API

The `plain-react.jsx` module provides everything needed on the client side. It is copied into your project when you run `plain react init`.

### `createPlainApp`

Bootstraps the React application. Call this in your `main.jsx` entry point:

```jsx
import { createPlainApp } from "./plain-react";

createPlainApp({
  resolve: (name) => {
    const pages = import.meta.glob("./pages/**/*.jsx", { eager: true });
    const page = pages[`./pages/${name}.jsx`];
    if (!page) throw new Error(`Page "${name}" not found.`);
    return page;
  },
});
```

### `usePage`

Access the current page data from any component:

```jsx
import { usePage } from "./plain-react";

function UserGreeting() {
  const { props, url, component } = usePage();
  return <p>Hello, {props.auth.user.name}!</p>;
}
```

### `Link`

SPA navigation component that fetches the next page as JSON instead of doing a full page load:

```jsx
import { Link } from "./plain-react";

<Link href="/users">Users</Link>
<Link href="/users" method="post" data={{ name: "John" }}>Create</Link>
<Link href="/logout" method="post" as="button">Logout</Link>
```

Modifier clicks (Ctrl+click, Cmd+click) are handled normally by the browser.

### `useForm`

Form state management with server submission:

```jsx
import { useForm } from "./plain-react";

function CreateUser() {
  const form = useForm({ name: "", email: "" });

  function handleSubmit(e) {
    e.preventDefault();
    form.post("/users");
  }

  return (
    <form onSubmit={handleSubmit}>
      <input
        value={form.data.name}
        onChange={(e) => form.setData("name", e.target.value)}
      />
      {form.errors.name && <span>{form.errors.name}</span>}
      <button disabled={form.processing}>Save</button>
    </form>
  );
}
```

The hook returns `data`, `setData`, `errors`, `hasErrors`, `processing`, `recentlySuccessful`, `isDirty`, `reset`, `clearErrors`, and HTTP method helpers (`get`, `post`, `put`, `patch`, `delete`).

### `router`

Programmatic navigation from anywhere (not just components):

```jsx
import { router } from "./plain-react";

// Navigate
router.visit("/users", { method: "GET" });
router.post("/users", { name: "John" });

// Reload current page
router.reload();

// Listen to navigation events
const off = router.on((event, data) => {
  if (event === "start") showSpinner();
  if (event === "finish") hideSpinner();
});
```

## React islands

If you primarily use Jinja2 templates but need React for specific interactive components (a chart, a data grid, a rich editor), you can embed individual React components using the `{% react %}` template tag.

### Template tag

The `{% react %}` tag renders a mount point for a single React component:

```html
<!-- In a Jinja2 template -->
<h1>Dashboard</h1>

{% react "RevenueChart" data=chart_data period="monthly" %}

<p>Some regular HTML content...</p>

{% react "ActivityFeed" items=recent_activity %}
```

Each tag renders a `<div>` with `data-react-component` and `data-react-props` attributes. The client-side runtime picks these up and mounts the React components.

### `mountIslands`

In your JavaScript entry point, call `mountIslands` to activate the template tag mount points:

```jsx
import { mountIslands } from "./plain-react";

mountIslands({
  resolve: (name) => {
    const components = import.meta.glob("./components/**/*.jsx", { eager: true });
    return components[`./components/${name}.jsx`];
  },
});
```

You can use both `createPlainApp` (full-page React) and `mountIslands` (islands in Jinja2 templates) in the same project if different pages need different approaches.

## Middleware

[`ReactMiddleware`](./middleware.py#ReactMiddleware) handles the SPA navigation protocol. It converts 302 redirects to 303 for PUT/PATCH/DELETE/POST requests, preventing browsers from re-submitting with the original HTTP method after a redirect.

```python
# app/settings.py
MIDDLEWARE = [
    "plain.react.middleware.ReactMiddleware",
    # ...
]
```

## Settings

Configure the React integration in your app settings:

```python
# app/settings.py
REACT = {
    "title": "My App",                         # <title> tag for the HTML shell
    "root_id": "app",                           # Root element ID (default: "app")
    "head": '<link rel="icon" href="/favicon.ico">',  # Extra content for <head>
    "vite_dev_url": "http://localhost:5173",     # Vite dev server URL
}
```

| Setting        | Default                   | Purpose                     |
| -------------- | ------------------------- | --------------------------- |
| `title`        | `""`                      | HTML `<title>` tag content  |
| `root_id`      | `"app"`                   | Root element ID             |
| `head`         | `""`                      | Extra `<head>` HTML content |
| `vite_dev_url` | `"http://localhost:5173"` | Vite dev server URL         |

## FAQs

#### How is this different from building a REST API + React SPA?

With a traditional API approach, you define API endpoints, manage client-side routing, handle loading states, and synchronize URL state between client and server. With `plain.react`, the server owns the routing and data loading — React just renders what the server tells it to. There's no client-side router, no API endpoints to maintain, and no loading state management for page transitions.

#### Can I use TypeScript?

Yes. Vite handles TypeScript out of the box. Name your files `.tsx` instead of `.jsx` and update the `resolve` function's glob pattern accordingly.

#### How does the Vite dev server integrate?

When `DEBUG` is true, the HTML shell loads scripts from the Vite dev server for hot module replacement (HMR). In production, it loads the compiled assets from `app/assets/react/`. The Vite dev server runs automatically alongside `plain dev`.

#### How do I deploy?

Run `plain react build` (or `plain build`) as part of your deployment. This produces optimized assets in `app/assets/react/`. Add `app/assets/react/` and `node_modules/` to your `.gitignore`.

#### Can I use both full-page React and React islands?

Yes. Use `ReactView` for pages that are entirely React, and `{% react %}` for embedding individual components in Jinja2 templates. They can coexist in the same project.

## Installation

Install the `plain.react` package from [PyPI](https://pypi.org/project/plain.react/):

```bash
uv add plain.react
```

Add `plain.react` to your `INSTALLED_PACKAGES` and the middleware:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.react",
]

MIDDLEWARE = [
    "plain.react.middleware.ReactMiddleware",
    # ...
]
```

Initialize the React project (creates `package.json`, `vite.config.js`, and starter files):

```bash
plain react init
```

Add these to your `.gitignore`:

```
node_modules/
app/assets/react/
```

Create a view and wire it up:

```python
# app/urls.py
from plain.urls import Router, path
from . import views

routes = Router([
    path("", views.IndexView),
])

# app/views.py
from plain.react.views import ReactView


class IndexView(ReactView):
    component = "Index"

    def get_props(self):
        return {"greeting": "Hello from Plain!"}
```

Start developing:

```bash
plain dev
```

The Vite dev server starts automatically alongside Plain, giving you hot module replacement for your React components.
