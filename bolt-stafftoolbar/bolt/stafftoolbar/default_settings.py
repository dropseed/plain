from bolt.urls import reverse_lazy

STAFFTOOLBAR_LINKS = [
    ("Admin", reverse_lazy("admin:index")),
]

STAFFTOOLBAR_CLASS = "bolt.stafftoolbar.StaffToolbar"
