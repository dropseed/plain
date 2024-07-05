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
});
