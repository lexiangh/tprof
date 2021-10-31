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

package adjuster

import (
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/jaegertracing/jaeger/model"
)

func TestSpanReferencesAdjuster(t *testing.T) {
	trace := &model.Trace{
		Spans: []*model.Span{
			{},
			{
				References: []model.SpanRef{},
			},
			{
				References: []model.SpanRef{
					{TraceID: model.NewTraceID(0, 1)},
					{TraceID: model.NewTraceID(1, 0)},
					{TraceID: model.NewTraceID(0, 0)},
				},
			},
		},
	}
	trace, err := SpanReferences().Adjust(trace)
	assert.NoError(t, err)
	assert.Len(t, trace.Spans[0].References, 0)
	assert.Len(t, trace.Spans[1].References, 0)
	assert.Len(t, trace.Spans[2].References, 2)
	assert.Contains(t, trace.Spans[2].Warnings[0], "Invalid span reference removed")
}
