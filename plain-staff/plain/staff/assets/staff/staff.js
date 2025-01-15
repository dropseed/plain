jQuery(function($) {
    $("[data-toggle]").on("click", function(e) {
        e.preventDefault();
        var targets = $(this).data("toggle").split(",");
        $.each(targets, function(index, target) {
            var $target = $(target);
            if ($target.data("toggle-class")) {
                $target.toggleClass($target.data("toggle-class"));
            } else {
                $target.toggle();
            }
        });
    });

    $("[data-autosubmit]").on("change", function(e) {
        $(this).closest("form").submit();
    });

    function createDropdowns(target) {
        $(target).find("[data-dropdown]").each(function() {
            var template = this.querySelector("template");
            tippy(this, {
                content: template.innerHTML,
                trigger: "click",
                allowHTML: true,
                interactive: true,
                duration: 100,
                placement: "bottom-end",
                offset: [0, 6],
                arrow: false,
                appendTo: () => document.body,
                onCreate: (instance) => {
                    instance.popper.classList.add("*:bg-white")
                    instance.popper.classList.add("*:w-48")
                    instance.popper.classList.add("*:rounded-md")
                    instance.popper.classList.add("*:shadow-lg")
                    instance.popper.classList.add("*:ring-1")
                    instance.popper.classList.add("*:ring-black")
                    instance.popper.classList.add("*:ring-opacity-5")
                },
            });
        });
    }

    function createTooltips(target) {
        $(target).find("[data-tooltip]").each(function() {
            tippy(this, {
                content: this.dataset.tooltip,
                duration: 100,
            });
        });
    }

    function autolinkColumns(target) {
        $(target).find("[data-column-autolink]").each(function() {
            var $this = $(this);
            if ($this.find("a").length > 0) {
                // Column already has a link, so don't add another
                return;
            }
            var $link = $(document.createElement("a"));
            $link.attr("href", $this.data("column-autolink"));
            $link.addClass("flex p-2 -m-2 text-black hover:no-underline");
            $(this).wrapInner($link);
        })
    }

    createDropdowns(document);
    createTooltips(document);
    autolinkColumns(document);

    // Search uses htmx to load elements,
    // so we need to hook those up too.
    htmx.on("htmx:afterSwap", function(evt) {
        createDropdowns(evt.detail.target);
        createTooltips(evt.detail.target);
        autolinkColumns(evt.detail.target);
    });
});
