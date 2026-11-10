// Startet den Editor (TinyMCE) für alle Textfelder mit data-editor="tinymce".
// Die erlaubten Elemente entsprechen der Bereinigung auf dem Server (seiten/models.py).
(function () {
  "use strict";
  if (!window.tinymce) { return; }

  var basis = document.currentScript.dataset.basis; // .../vendor/tinymce

  window.tinymce.init({
    selector: "textarea[data-editor=tinymce]",
    license_key: "gpl",
    base_url: basis,
    suffix: ".min",
    language: "de",
    language_url: basis + "/langs/de.js",
    menubar: false,
    branding: false,
    promotion: false,
    statusbar: true,
    elementpath: false,
    height: 480,
    plugins: "lists link table autolink",
    toolbar: "undo redo | blocks | bold italic underline | bullist numlist | link table | removeformat",
    block_formats: "Absatz=p; Überschrift=h2; Unterüberschrift=h3; Zitat=blockquote",
    valid_elements:
      "p,br,strong/b,em/i,u,s,sub,sup,h2,h3,h4,ul,ol,li,blockquote,hr," +
      "a[href|title],table,thead,tbody,tr,th[colspan|rowspan],td[colspan|rowspan],caption",
    invalid_styles: "*",
    table_default_attributes: {},
    table_default_styles: {},
    table_sizing_mode: "relative",
    link_default_protocol: "https",
    link_assume_external_targets: true,
    target_list: false,
    convert_urls: false,
    entity_encoding: "raw",
    paste_as_text: false,
    content_css: "default",
  });
})();
