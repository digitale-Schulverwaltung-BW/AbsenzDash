<?php
/**
 * Plugin Name: AbsenzDash
 * Description: Reverse-Proxy und Shortcode-Einbindung fuer die AbsenzDash-SPA im Schulintranet.
 * Version: 0.1.0
 * Requires at least: 5.6
 * Requires PHP: 7.4
 * Author: HHS Karlsruhe
 * License: GPL-2.0-or-later
 * Text Domain: absenzdash
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'ABSENZDASH_PLUGIN_DIR', plugin_dir_path( __FILE__ ) );
define( 'ABSENZDASH_PLUGIN_URL', plugin_dir_url( __FILE__ ) );
define( 'ABSENZDASH_VERSION', '0.1.0' );

require_once ABSENZDASH_PLUGIN_DIR . 'includes/class-optionen.php';
require_once ABSENZDASH_PLUGIN_DIR . 'includes/class-proxy.php';
require_once ABSENZDASH_PLUGIN_DIR . 'includes/class-shortcode.php';
require_once ABSENZDASH_PLUGIN_DIR . 'includes/class-rollen-seite.php';
require_once ABSENZDASH_PLUGIN_DIR . 'includes/class-bereiche-seite.php';

add_action(
	'plugins_loaded',
	function () {
		new Absenzdash_Optionen();
		new Absenzdash_Proxy();
		new Absenzdash_Shortcode();
		new Absenzdash_Rollen_Seite();
		new Absenzdash_Bereiche_Seite();
	}
);
