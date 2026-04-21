# Architecture Rules

This document defines the **mandatory architecture conventions** for this project.

It is intended to guide:

- developers
- AI coding assistants
- code generation tools

The rules in this document are **architecture rules only**.

They intentionally avoid:

- framework-specific decisions
- domain-specific logic
- endpoint definitions
- infrastructure concerns

The goal is to ensure the project structure remains **clear, scalable, predictable, and easy to reason about**, following principles inspired by **Laravel architecture and SOLID design principles**.

---

# Core Philosophy

The architecture must prioritize:

- clarity
- explicit responsibilities
- maintainability
- simplicity of navigation

Every contributor should be able to open the project and immediately understand:

- where logic lives
- what each class is responsible for
- how responsibilities are separated

The architecture should feel **boring in a good way**.

Predictability is preferred over cleverness.

---

# Laravel‑Inspired Architecture

This project adopts several structural ideas inspired by Laravel.

These ideas are used because they produce codebases that are:

- easy to navigate
- easy to maintain
- easy to scale
- easy for new contributors to understand

Key concepts adopted from Laravel:

### Domain‑oriented organization

Code is grouped by **capability or responsibility**, not by technical type alone.

Bad example:

```
services/
  image_service
  render_service
  mask_service
```

Good example:

```
app/
  services/
    image/
    segmentation/
    render/
```

Each folder represents a **clear responsibility area**.

---

### Thin entry points

Entry points (routes, controllers, CLI commands, etc.) must remain thin.

They should only:

- receive input
- validate input
- call a service
- return a response

They must not contain:

- business logic
- image processing logic
- storage logic
- orchestration logic

---

### Action‑oriented services

Business logic is implemented through **small, focused services**.

Services represent **specific actions**, not broad toolboxes.

Example naming style:

```
StoreUploadedImage
LoadImageById
DeleteImage
GenerateSegmentationsFromImage
StoreConfirmedMask
ApplyWallColor
```

Each service must describe **a clear action**.

---

# Folder Structure Principles

The project should follow a structure similar to the following:

```
app/
  services/
  repositories/
  models/
  utils/

routes/

config/

storage/
```

### app/

Contains the core application logic.

### services/

Contains **action‑oriented service classes**.

Services implement business logic.

Services must remain small and focused.

Services may be grouped into subfolders representing capability areas.

Example:

```
app/services/
  image/
  segmentation/
  mask/
  render/
```

Each subfolder contains services related to that capability.

---

### repositories/

Repositories are responsible for **data persistence and retrieval**.

Repositories should contain logic related to:

- loading
- storing
- deleting
- updating

Repositories must not contain business logic.

Example:

```
ImageRepository
MaskRepository
RenderRepository
```

---

### models/

Models represent structured data objects used by the application.

They should contain minimal logic.

Models exist primarily to represent data structures.

---

### utils/

Utilities contain **small reusable helper functions**.

Utilities must be cohesive.

They must not become dumping grounds for unrelated logic.

Bad example:

```
helpers.py
```

Good example:

```
image_dimensions.py
hex_color_conversion.py
mask_encoding.py
hex_color.py
```

---

### Value objects

Value objects encapsulate domain concepts with validation and immutability.

Use them when:

- A value has strict validation rules (e.g. HEX color, email, UUID string).
- The same validation is needed in multiple places.
- The concept deserves a named type for clarity.

In Python, value objects are typically:

- A class that validates on construction and raises on invalid input.
- Immutable (no setters; store in private attribute).
- Expose the value via a property or `__str__`.

Place them in `app/utils/` when they are generic (e.g. `hex_color.py`).
Place them in `app/models/value_objects/` when they are domain-specific and used across services.

Example:

```python
# app/utils/hex_color.py
class HexColor:
    def __init__(self, value: str):
        if not re.match(r"^#[0-9a-fA-F]{6}$", value):
            raise ValueError(f"Invalid HEX color: {value}")
        self._value = value

    @property
    def value(self) -> str:
        return self._value
```

---

### routes/

Routes define application entry points.

Routes should remain simple and centralized.

A single route file is acceptable and encouraged for simplicity.

Routes should map directly to service calls.

---

### storage/

Contains stored assets and files.

Example structure:

```
storage/
  uploads/
  masks/
  renders/
```

Original files must remain immutable.

Generated outputs must never overwrite originals.

---

# Service Design Rules

Services are the **core of the architecture**.

They must follow strict design principles.

---

### One service = one responsibility

Each service should perform **one clear action**.

Bad:

```
ImageProcessingService
```

Good:

```
StoreUploadedImage
LoadImageById
DeleteImage
```

If a class name contains "and", it likely violates single responsibility.

---

### Services must be explicit

Avoid vague names such as:

```
Service
Manager
Handler
Helper
Processor
Utils
```

Prefer descriptive names that explain the action.

---

### Services should orchestrate, not do everything

A service may coordinate multiple operations, but complex tasks should still be delegated.

Example:

```
GenerateSegmentationsFromImage
```

This service may call:

- image loader
- segmentation model
- segmentation filter
- segmentation storage

But each of those responsibilities should remain isolated.

---

# Repository Rules

Repositories isolate persistence logic.

Responsibilities include:

- reading data
- writing data
- deleting data

Repositories must not contain business rules.

Repositories must not perform image processing.

Repositories must not orchestrate workflows.

### Query interface

Every repository must expose exactly two query entry points for reads:

- `find(id, relationships: list[str] | None = None)` — load a single row by primary key; returns the entity or `None`. When `relationships` is set, each name must be a SQLAlchemy relationship on the model; use `joinedload` for every listed name to avoid N+1 queries.
- `find_by(criteria: dict, relationships: list[str] | None = None)` — filter by model column names and values; returns a **list** (empty if no matches). Same `relationships` / `joinedload` behavior as `find`.

Do **not** add ad‑hoc methods such as `find_by_id`, `get_by_id`, `find_by_slug`, or `find_by_product_code`. Express those lookups via `find` (when querying by id) or `find_by({"column": value, ...})`.

Use `save(entity)` to persist new or updated model instances (`add`, `commit`, `refresh`) instead of repository methods with long parameter lists, unless a specialized bulk API is justified.

You may add other non-query helpers (`update`, domain-specific `search`, etc.) as needed. Optional default ordering inside `find_by` (e.g. by `created_at` or `name`) is allowed when it keeps list endpoints predictable.

### Update pattern

Prefer a single `update(id, **kwargs)` method over multiple update methods per field.

- Whitelist updatable fields to avoid accidental or arbitrary updates.
- Keeps the interface small (Open/Closed: new fields do not require new methods).
- Reduces duplication of find-modify-commit logic.

Example:

```python
def update(self, entity_id: str, **kwargs) -> Entity:
    entity = self.find(entity_id)
    if entity is None:
        raise ValueError("Entity not found")
    allowed = {"status", "result_path"}  # whitelist
    for key, value in kwargs.items():
        if key in allowed:
            setattr(entity, key, value)
    self.db.commit()
    self.db.refresh(entity)
    return entity
```

---

# SOLID Principles

This architecture follows SOLID design principles.

---

### Single Responsibility Principle

Every class must have one reason to change.

Classes that handle multiple responsibilities must be split.

---

### Open/Closed Principle

Code should be extendable without rewriting core logic.

When a new capability is introduced, it should be added through new classes rather than modifying existing behavior.

---

### Liskov Substitution Principle

Inheritance should not break expected behavior.

Use inheritance sparingly.

Prefer composition.

---

### Interface Segregation Principle

Interfaces should remain small and focused.

Do not create large interfaces covering unrelated behaviors.

---

### Dependency Inversion Principle

High‑level modules should not depend directly on low‑level implementation details.

Dependencies should be injected when appropriate.

---

# Naming Conventions

Clear naming is essential for maintainability.

### Class naming

Use **verb‑based names for actions**.

Examples:

```
StoreUploadedImage
LoadImageById
GenerateSegmentationsFromImage
StoreConfirmedMask
ApplyWallColor
```

---

### Repository naming

Repositories should follow this pattern:

```
EntityRepository
```

Examples:

```
ImageRepository
MaskRepository
RenderRepository
```

---

### File naming

Use descriptive filenames matching the class responsibility.

Avoid vague filenames.

---

# Anti‑Patterns

The following patterns are forbidden:

### Generic service classes

```
ImageService
ProcessingService
UtilityService
```

### Large monolithic helpers

```
helpers.py
utils.py
```

### Business logic inside routes

Routes must never contain core logic.

### God classes

Classes responsible for multiple concerns must be split.

---

# Code Generation Rules for AI Assistants

When generating code for this project, AI tools must follow these rules:

1. Always place code inside the correct architectural layer.
2. Prefer creating new small services rather than expanding existing ones.
3. Never create a generic service class.
4. Keep entry points thin.
5. Respect the folder structure.
6. Avoid adding abstraction layers unless necessary.
7. Prefer clarity over clever patterns.

---

# Architecture Guiding Principle

The architecture should always remain:

- predictable
- readable
- explicit
- modular

When a design decision must be made, choose the option that produces the **most understandable codebase**, not the most technically sophisticated one.

In this guide we gave examples as camelCase, but you can use snake_case if you prefer depending on the language.

---

# Comment Rules

Code should be descriptive enough to be understood without comments.

Use comments only when they are essential to explain context that is not clear from names or structure.

When a comment is required:

- write it in English
- use simple words
- keep it short and direct

Avoid comments that repeat what the code already says.
