// Copyright (c) 2019 The Jaeger Authors.
// Copyright (c) 2017 Uber Technologies, Inc.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package cassandra

import (
	"flag"
	"strings"
	"time"

	"github.com/spf13/viper"

	"github.com/jaegertracing/jaeger/pkg/cassandra/config"
)

const (
	// session settings
	suffixEnabled              = ".enabled"
	suffixConnPerHost          = ".connections-per-host"
	suffixMaxRetryAttempts     = ".max-retry-attempts"
	suffixTimeout              = ".timeout"
	suffixConnectTimeout       = ".connect-timeout"
	suffixReconnectInterval    = ".reconnect-interval"
	suffixServers              = ".servers"
	suffixPort                 = ".port"
	suffixKeyspace             = ".keyspace"
	suffixDC                   = ".local-dc"
	suffixConsistency          = ".consistency"
	suffixDisableCompression   = ".disable-compression"
	suffixProtoVer             = ".proto-version"
	suffixSocketKeepAlive      = ".socket-keep-alive"
	suffixUsername             = ".username"
	suffixPassword             = ".password"
	suffixTLS                  = ".tls"
	suffixCert                 = ".tls.cert"
	suffixKey                  = ".tls.key"
	suffixCA                   = ".tls.ca"
	suffixServerName           = ".tls.server-name"
	suffixVerifyHost           = ".tls.verify-host"
	suffixEnableDependenciesV2 = ".enable-dependencies-v2"

	// common storage settings
	suffixSpanStoreWriteCacheTTL = ".span-store-write-cache-ttl"
	suffixIndexTagsBlacklist     = ".index.tag-blacklist"
	suffixIndexTagsWhitelist     = ".index.tag-whitelist"
	suffixIndexLogs              = ".index.logs"
	suffixIndexTags              = ".index.tags"
	suffixIndexProcessTags       = ".index.process-tags"
)

// Options contains various type of Cassandra configs and provides the ability
// to bind them to command line flag and apply overlays, so that some configurations
// (e.g. archive) may be underspecified and infer the rest of its parameters from primary.
type Options struct {
	primary                 *namespaceConfig
	others                  map[string]*namespaceConfig
	SpanStoreWriteCacheTTL  time.Duration
	tagIndexBlacklist       string
	tagIndexWhitelist       string
	DisableLogsIndex        bool
	DisableTagsIndex        bool
	DisableProcessTagsIndex bool
}

// the Servers field in config.Configuration is a list, which we cannot represent with flags.
// This struct adds a plain string field that can be bound to flags and is then parsed when
// preparing the actual config.Configuration.
type namespaceConfig struct {
	config.Configuration
	servers   string
	namespace string
	primary   bool
	Enabled   bool
}

// NewOptions creates a new Options struct.
func NewOptions(primaryNamespace string, otherNamespaces ...string) *Options {
	// TODO all default values should be defined via cobra flags
	options := &Options{
		primary: &namespaceConfig{
			Configuration: config.Configuration{
				TLS: config.TLS{
					Enabled:                false,
					EnableHostVerification: true,
				},
				MaxRetryAttempts:   3,
				Keyspace:           "jaeger_v1_test",
				ProtoVersion:       4,
				ConnectionsPerHost: 2,
				ReconnectInterval:  60 * time.Second,
			},
			servers:   "127.0.0.1",
			namespace: primaryNamespace,
			primary:   true,
			Enabled:   true,
		},
		others:                 make(map[string]*namespaceConfig, len(otherNamespaces)),
		SpanStoreWriteCacheTTL: time.Hour * 12,
	}

	for _, namespace := range otherNamespaces {
		options.others[namespace] = &namespaceConfig{namespace: namespace}
	}

	return options
}

// AddFlags adds flags for Options
func (opt *Options) AddFlags(flagSet *flag.FlagSet) {
	addFlags(flagSet, opt.primary)
	for _, cfg := range opt.others {
		addFlags(flagSet, cfg)
	}
	flagSet.Duration(opt.primary.namespace+suffixSpanStoreWriteCacheTTL,
		opt.SpanStoreWriteCacheTTL,
		"The duration to wait before rewriting an existing service or operation name")
	flagSet.String(
		opt.primary.namespace+suffixIndexTagsBlacklist,
		opt.tagIndexBlacklist,
		"The comma-separated list of span tags to blacklist from being indexed. All other tags will be indexed. Mutually exclusive with the whitelist option.")
	flagSet.String(
		opt.primary.namespace+suffixIndexTagsWhitelist,
		opt.tagIndexWhitelist,
		"The comma-separated list of span tags to whitelist for being indexed. All other tags will not be indexed. Mutually exclusive with the blacklist option.")
	flagSet.Bool(
		opt.primary.namespace+suffixIndexLogs,
		!opt.DisableLogsIndex,
		"Controls log field indexing. Set to false to disable.")
	flagSet.Bool(
		opt.primary.namespace+suffixIndexTags,
		!opt.DisableTagsIndex,
		"Controls tag indexing. Set to false to disable.")
	flagSet.Bool(
		opt.primary.namespace+suffixIndexProcessTags,
		!opt.DisableProcessTagsIndex,
		"Controls process tag indexing. Set to false to disable.")
}

func addFlags(flagSet *flag.FlagSet, nsConfig *namespaceConfig) {
	if !nsConfig.primary {
		flagSet.Bool(
			nsConfig.namespace+suffixEnabled,
			false,
			"Enable extra storage")
	}
	flagSet.Int(
		nsConfig.namespace+suffixConnPerHost,
		nsConfig.ConnectionsPerHost,
		"The number of Cassandra connections from a single backend instance")
	flagSet.Int(
		nsConfig.namespace+suffixMaxRetryAttempts,
		nsConfig.MaxRetryAttempts,
		"The number of attempts when reading from Cassandra")
	flagSet.Duration(
		nsConfig.namespace+suffixTimeout,
		nsConfig.Timeout,
		"Timeout used for queries. A Timeout of zero means no timeout")
	flagSet.Duration(
		nsConfig.namespace+suffixConnectTimeout,
		nsConfig.ConnectTimeout,
		"Timeout used for connections to Cassandra Servers")
	flagSet.Duration(
		nsConfig.namespace+suffixReconnectInterval,
		nsConfig.ReconnectInterval,
		"Reconnect interval to retry connecting to downed hosts")
	flagSet.String(
		nsConfig.namespace+suffixServers,
		nsConfig.servers,
		"The comma-separated list of Cassandra servers")
	flagSet.Int(
		nsConfig.namespace+suffixPort,
		nsConfig.Port,
		"The port for cassandra")
	flagSet.String(
		nsConfig.namespace+suffixKeyspace,
		nsConfig.Keyspace,
		"The Cassandra keyspace for Jaeger data")
	flagSet.String(
		nsConfig.namespace+suffixDC,
		nsConfig.LocalDC,
		"The name of the Cassandra local data center for DC Aware host selection")
	flagSet.String(
		nsConfig.namespace+suffixConsistency,
		nsConfig.Consistency,
		"The Cassandra consistency level, e.g. ANY, ONE, TWO, THREE, QUORUM, ALL, LOCAL_QUORUM, EACH_QUORUM, LOCAL_ONE (default LOCAL_ONE)")
	flagSet.Bool(
		nsConfig.namespace+suffixDisableCompression,
		false,
		"Disables the use of the default Snappy Compression while connecting to the Cassandra Cluster if set to true. This is useful for connecting to Cassandra Clusters(like Azure Cosmos Db with Cassandra API) that do not support SnappyCompression")
	flagSet.Int(
		nsConfig.namespace+suffixProtoVer,
		nsConfig.ProtoVersion,
		"The Cassandra protocol version")
	flagSet.Duration(
		nsConfig.namespace+suffixSocketKeepAlive,
		nsConfig.SocketKeepAlive,
		"Cassandra's keepalive period to use, enabled if > 0")
	flagSet.String(
		nsConfig.namespace+suffixUsername,
		nsConfig.Authenticator.Basic.Username,
		"Username for password authentication for Cassandra")
	flagSet.String(
		nsConfig.namespace+suffixPassword,
		nsConfig.Authenticator.Basic.Password,
		"Password for password authentication for Cassandra")
	flagSet.Bool(
		nsConfig.namespace+suffixTLS,
		nsConfig.TLS.Enabled,
		"Enable TLS")
	flagSet.String(
		nsConfig.namespace+suffixCert,
		nsConfig.TLS.CertPath,
		"Path to TLS certificate file")
	flagSet.String(
		nsConfig.namespace+suffixKey,
		nsConfig.TLS.KeyPath,
		"Path to TLS key file")
	flagSet.String(
		nsConfig.namespace+suffixCA,
		nsConfig.TLS.CaPath,
		"Path to TLS CA file")
	flagSet.String(
		nsConfig.namespace+suffixServerName,
		nsConfig.TLS.ServerName,
		"Override the TLS server name")
	flagSet.Bool(
		nsConfig.namespace+suffixVerifyHost,
		nsConfig.TLS.EnableHostVerification,
		"Enable (or disable) host key verification")
	flagSet.Bool(
		nsConfig.namespace+suffixEnableDependenciesV2,
		nsConfig.EnableDependenciesV2,
		"(deprecated) Jaeger will automatically detect the version of the dependencies table")
}

// InitFromViper initializes Options with properties from viper
func (opt *Options) InitFromViper(v *viper.Viper) {
	opt.primary.initFromViper(v)
	for _, cfg := range opt.others {
		cfg.initFromViper(v)
	}
	opt.SpanStoreWriteCacheTTL = v.GetDuration(opt.primary.namespace + suffixSpanStoreWriteCacheTTL)
	opt.tagIndexBlacklist = stripWhiteSpace(v.GetString(opt.primary.namespace + suffixIndexTagsBlacklist))
	opt.tagIndexWhitelist = stripWhiteSpace(v.GetString(opt.primary.namespace + suffixIndexTagsWhitelist))
	opt.DisableTagsIndex = !v.GetBool(opt.primary.namespace + suffixIndexTags)
	opt.DisableLogsIndex = !v.GetBool(opt.primary.namespace + suffixIndexLogs)
	opt.DisableProcessTagsIndex = !v.GetBool(opt.primary.namespace + suffixIndexProcessTags)
}

func (cfg *namespaceConfig) initFromViper(v *viper.Viper) {
	if !cfg.primary {
		cfg.Enabled = v.GetBool(cfg.namespace + suffixEnabled)
	}
	cfg.ConnectionsPerHost = v.GetInt(cfg.namespace + suffixConnPerHost)
	cfg.MaxRetryAttempts = v.GetInt(cfg.namespace + suffixMaxRetryAttempts)
	cfg.Timeout = v.GetDuration(cfg.namespace + suffixTimeout)
	cfg.ConnectTimeout = v.GetDuration(cfg.namespace + suffixConnectTimeout)
	cfg.ReconnectInterval = v.GetDuration(cfg.namespace + suffixReconnectInterval)
	cfg.servers = stripWhiteSpace(v.GetString(cfg.namespace + suffixServers))
	cfg.Port = v.GetInt(cfg.namespace + suffixPort)
	cfg.Keyspace = v.GetString(cfg.namespace + suffixKeyspace)
	cfg.LocalDC = v.GetString(cfg.namespace + suffixDC)
	cfg.Consistency = v.GetString(cfg.namespace + suffixConsistency)
	cfg.ProtoVersion = v.GetInt(cfg.namespace + suffixProtoVer)
	cfg.SocketKeepAlive = v.GetDuration(cfg.namespace + suffixSocketKeepAlive)
	cfg.Authenticator.Basic.Username = v.GetString(cfg.namespace + suffixUsername)
	cfg.Authenticator.Basic.Password = v.GetString(cfg.namespace + suffixPassword)
	cfg.TLS.Enabled = v.GetBool(cfg.namespace + suffixTLS)
	cfg.TLS.CertPath = v.GetString(cfg.namespace + suffixCert)
	cfg.TLS.KeyPath = v.GetString(cfg.namespace + suffixKey)
	cfg.TLS.CaPath = v.GetString(cfg.namespace + suffixCA)
	cfg.TLS.ServerName = v.GetString(cfg.namespace + suffixServerName)
	cfg.TLS.EnableHostVerification = v.GetBool(cfg.namespace + suffixVerifyHost)
	cfg.EnableDependenciesV2 = v.GetBool(cfg.namespace + suffixEnableDependenciesV2)
	cfg.DisableCompression = v.GetBool(cfg.namespace + suffixDisableCompression)
}

// GetPrimary returns primary configuration.
func (opt *Options) GetPrimary() *config.Configuration {
	opt.primary.Servers = strings.Split(opt.primary.servers, ",")
	return &opt.primary.Configuration
}

// Get returns auxiliary named configuration.
func (opt *Options) Get(namespace string) *config.Configuration {
	nsCfg, ok := opt.others[namespace]
	if !ok {
		nsCfg = &namespaceConfig{}
		opt.others[namespace] = nsCfg
	}
	if !nsCfg.Enabled {
		return nil
	}
	nsCfg.Configuration.ApplyDefaults(&opt.primary.Configuration)
	if nsCfg.servers == "" {
		nsCfg.servers = opt.primary.servers
	}
	nsCfg.Servers = strings.Split(nsCfg.servers, ",")
	return &nsCfg.Configuration
}

// TagIndexBlacklist returns the list of blacklisted tags
func (opt *Options) TagIndexBlacklist() []string {
	if len(opt.tagIndexBlacklist) > 0 {
		return strings.Split(opt.tagIndexBlacklist, ",")
	}

	return nil
}

// TagIndexWhitelist returns the list of whitelisted tags
func (opt *Options) TagIndexWhitelist() []string {
	if len(opt.tagIndexWhitelist) > 0 {
		return strings.Split(opt.tagIndexWhitelist, ",")
	}

	return nil
}

// stripWhiteSpace removes all whitespace characters from a string
func stripWhiteSpace(str string) string {
	return strings.Replace(str, " ", "", -1)
}
