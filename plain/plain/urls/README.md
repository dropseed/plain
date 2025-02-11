# urls

Route requests to views.

## Usage

Use the `path()` function to define URL patterns.

```python
from plain.urls import path
from . import views

urlpatterns = [
    path('', views.home_view),
    path('about/', views.about_view),
]
```
